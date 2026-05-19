"""
AitapClient — Python WebSocket client for the aitap relay server.

Provides a reusable, asyncio-based client that:
  • Connects to ws://localhost:3000 (or any relay URL)
  • Receives and stores its clientId from the welcome handshake
  • Listens for incoming messages from other clients
  • Sends messages to specific targets or broadcasts
  • Auto-reconnects with exponential back-off
  • Logs everything for debugging

Usage:
    import asyncio
    from aitap_client import AitapClient

    async def main():
        client = AitapClient(uri="ws://localhost:3000")
        await client.connect()
        await client.send(target="openclaw", payload={"cmd": "ping"})
        await asyncio.sleep(30)
        await client.close()

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import websockets
from websockets.protocol import State

logger = logging.getLogger("aitap_client")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AitapMessage:
    """Normalized incoming message from the relay."""

    msg_type: str           # e.g. "welcome", "message", "ack"
    from_id: Optional[str]  # sender clientId (None for welcome)
    payload: Any            # string or dict
    raw: Dict[str, Any]     # original JSON object
    received_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class AitapClient:
    """
    Async WebSocket client for the aitap relay.

    Parameters
    ----------
    uri : str
        WebSocket URI of the relay (default: ws://localhost:3000).
    auto_reconnect : bool
        Whether to reconnect automatically on disconnect (default: True).
    reconnect_base_delay : float
        Initial delay in seconds before the first reconnection attempt.
    reconnect_max_delay : float
        Cap on reconnection back-off.
    reconnect_jitter : float
        Random factor added to back-off (0..1).
    on_message : Callable[[AitapMessage], None] | None
        Optional callback invoked for every incoming message.
    """

    def __init__(
        self,
        uri: str = "ws://localhost:3000",
        *,
        auto_reconnect: bool = True,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
        reconnect_jitter: float = 0.5,
        on_message: Optional[Callable[[AitapMessage], None]] = None,
    ):
        self.uri = uri
        self.auto_reconnect = auto_reconnect
        self.reconnect_base_delay = reconnect_base_delay
        self.reconnect_max_delay = reconnect_max_delay
        self.reconnect_jitter = reconnect_jitter
        self.on_message = on_message

        # Runtime state
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.client_id: Optional[str] = None
        self._running = False
        self._listener_task: Optional[asyncio.Task] = None
        self._reconnect_delay: float = reconnect_base_delay
        self._send_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._send_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect(self, *, wait_for_welcome: bool = True, welcome_timeout: float = 5.0) -> None:
        """Open the WebSocket and start the background listener.

        If *wait_for_welcome* is True (default), blocks until the relay
        sends the welcome handshake and *client_id* is populated.
        """
        if self._running:
            logger.warning("Client already connected or connecting.")
            return

        self._running = True
        await self._do_connect()
        self._listener_task = asyncio.create_task(
            self._listen_loop(), name="aitap-listener"
        )
        self._send_task = asyncio.create_task(
            self._send_loop(), name="aitap-sender"
        )

        if wait_for_welcome:
            deadline = asyncio.get_event_loop().time() + welcome_timeout
            while self.client_id is None:
                if asyncio.get_event_loop().time() > deadline:
                    raise TimeoutError("Did not receive welcome from relay within timeout")
                await asyncio.sleep(0.05)
            logger.info("AitapClient connected. client_id=%s", self.client_id)
        else:
            logger.info("AitapClient started. Waiting for welcome…")

    async def close(self) -> None:
        """Gracefully shut down the client."""
        self._running = False

        # Cancel background tasks
        for task in (self._listener_task, self._send_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self.ws:
            await self.ws.close()
            self.ws = None

        logger.info("AitapClient closed.")

    async def send(
        self,
        target: str,
        payload: Any,
        *,
        timeout: Optional[float] = 10.0,
    ) -> None:
        """
        Queue a message to be sent to *target* (clientId or 'broadcast').

        The message is placed on an internal queue and dispatched by a
        dedicated sender coroutine so that callers never block on the
        socket itself.
        """
        if not self._running:
            raise RuntimeError("Client is not connected. Call connect() first.")

        envelope = {
            "target": target,
            "payload": payload,
            "_queued_at": time.time(),
        }
        await asyncio.wait_for(self._send_queue.put(envelope), timeout=timeout)
        logger.debug("Queued message for target=%s", target)

    def is_connected(self) -> bool:
        """Return True if the WebSocket is open."""
        return self.ws is not None and self.ws.state is State.OPEN

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _do_connect(self) -> None:
        """Perform a single WebSocket connection attempt."""
        logger.info("Connecting to %s …", self.uri)
        try:
            self.ws = await websockets.connect(self.uri)
            logger.info("WebSocket connected.")
        except (OSError, websockets.InvalidURI, websockets.ConnectionClosed) as exc:
            logger.error("Connection failed: %s", exc)
            raise

    async def _listen_loop(self) -> None:
        """Main read loop — parses messages and triggers callbacks."""
        while self._running:
            try:
                if self.ws is None or self.ws.state is not State.OPEN:
                    if self.auto_reconnect:
                        await self._reconnect()
                        continue
                    else:
                        logger.error("Socket closed and auto_reconnect=False")
                        break

                raw_text = await self.ws.recv()
                msg = self._parse_message(raw_text)

                if msg is None:
                    continue

                # Handle welcome handshake
                if msg.msg_type == "welcome":
                    self.client_id = msg.raw.get("clientId")
                    self._reconnect_delay = self.reconnect_base_delay
                    logger.info(
                        "Received welcome — our clientId is %s", self.client_id
                    )

                # Invoke user callback if provided
                if self.on_message:
                    try:
                        self.on_message(msg)
                    except Exception:
                        logger.exception("Error in on_message callback")

            except websockets.ConnectionClosed as exc:
                logger.warning("Connection closed: %s", exc)
                self.ws = None
                if not self.auto_reconnect:
                    break
                await self._reconnect()
            except asyncio.CancelledError:
                logger.debug("Listener cancelled.")
                raise
            except Exception:
                logger.exception("Unexpected error in listener loop")
                if not self.auto_reconnect:
                    break
                await self._reconnect()

    async def _send_loop(self) -> None:
        """Drain the internal send queue over the WebSocket."""
        while self._running:
            try:
                envelope = await self._send_queue.get()
            except asyncio.CancelledError:
                raise

            # Wait until we have a live socket
            while self._running and (self.ws is None or self.ws.state is not State.OPEN):
                if not self.auto_reconnect:
                    logger.warning("Dropping message — not connected.")
                    break
                await asyncio.sleep(0.5)
            else:
                if self.ws and self.ws.state is State.OPEN:
                    # Strip internal metadata before serialising
                    payload = {
                        k: v for k, v in envelope.items() if not k.startswith("_")
                    }
                    try:
                        await self.ws.send(json.dumps(payload))
                        logger.debug("Sent message to %s", envelope.get("target"))
                    except websockets.ConnectionClosed:
                        logger.warning("Send failed — connection lost.")
                        # Put it back at the front of the queue
                        await self._send_queue.put(envelope)
                        self.ws = None

    async def _reconnect(self) -> None:
        """Back-off reconnection with jitter."""
        jitter = self.reconnect_jitter * (asyncio.get_event_loop().time() % 1)
        delay = min(
            self._reconnect_delay + jitter,
            self.reconnect_max_delay,
        )
        logger.info("Reconnecting in %.2f seconds…", delay)
        await asyncio.sleep(delay)

        try:
            await self._do_connect()
            # Next failure waits longer, up to the cap
            self._reconnect_delay = min(
                self._reconnect_delay * 2,
                self.reconnect_max_delay,
            )
        except Exception as exc:
            logger.error("Reconnection attempt failed: %s", exc)
            # Already increased delay above, so just loop again

    def _parse_message(self, raw_text: str) -> Optional[AitapMessage]:
        """Turn a raw JSON string into an AitapMessage."""
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.warning("Non-JSON message received: %s", exc)
            return None

        msg_type = data.get("type", "unknown")
        from_id = data.get("from") or data.get("clientId")
        payload = data.get("payload", data)

        return AitapMessage(
            msg_type=msg_type,
            from_id=from_id,
            payload=payload,
            raw=data,
        )


# ---------------------------------------------------------------------------
# Convenience synchronous wrapper (for quick scripts / REPL)
# ---------------------------------------------------------------------------

class SyncAitapClient:
    """
    Thin synchronous wrapper around AitapClient.

    Useful when you don't want to write ``asyncio.run`` everywhere.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        self._client = AitapClient(*args, **kwargs)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[asyncio.Task] = None

    def connect(self) -> None:
        """Block until the underlying async client is connected."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._client.connect())
        # Spin the event loop in a background task so send/recv keep working
        self._thread = self._loop.create_task(self._keep_alive())

    def close(self) -> None:
        if self._loop:
            self._loop.run_until_complete(self._client.close())
            self._loop.close()
            self._loop = None

    def send(self, target: str, payload: Any) -> None:
        if self._loop is None:
            raise RuntimeError("Not connected.")
        asyncio.run_coroutine_threadsafe(
            self._client.send(target, payload), self._loop
        )

    @property
    def client_id(self) -> Optional[str]:
        return self._client.client_id

    async def _keep_alive(self) -> None:
        """Placeholder to keep the loop alive — real work is in AitapClient tasks."""
        while self._client._running:
            await asyncio.sleep(1)
