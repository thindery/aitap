#!/usr/bin/env python3
"""
example.py — Demonstrates the AitapClient API.

Run two copies in separate terminals to chat, or run one copy and
send messages from another aitap client (e.g. openclaw).

    Terminal 1:
        python example.py

    Terminal 2:
        python example.py

Then, in either terminal, type a target clientId and a message.
"""

import asyncio
import logging
import sys

from aitap_client import AitapClient, AitapMessage

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------


def on_message(msg: AitapMessage) -> None:
    """Called for every incoming message (welcome, chat, ack, etc.)."""
    if msg.msg_type == "welcome":
        print(f"🤝  Welcome! Our clientId is {msg.from_id}")
    elif msg.msg_type == "message":
        sender = msg.from_id or "unknown"
        print(f"📨  Message from {sender}: {msg.payload}")
    elif msg.msg_type == "ack":
        print(f"✅  ACK received for message to {msg.raw.get('target')}")
    else:
        print(f"ℹ️   [{msg.msg_type}] {msg.payload}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    client = AitapClient(
        uri="ws://localhost:3000",
        on_message=on_message,
        auto_reconnect=True,
    )

    print("Connecting to aitap relay…")
    await client.connect()

    # Wait a moment for the welcome handshake
    for _ in range(20):
        if client.client_id:
            break
        await asyncio.sleep(0.1)

    if not client.client_id:
        print("Did not receive welcome in time. Exiting.")
        await client.close()
        sys.exit(1)

    print(f"\nYou are {client.client_id}")
    print("Commands:")
    print("  /to <clientId> <message>   — send a direct message")
    print("  /broadcast <message>        — send to everyone")
    print("  /quit                       — exit")
    print("")

    # Read commands from stdin in a background task
    async def stdin_reader():
        loop = asyncio.get_event_loop()
        while client._running:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            line = line.strip()
            if not line:
                continue

            if line == "/quit":
                await client.close()
                break

            if line.startswith("/to "):
                parts = line[4:].split(" ", 1)
                if len(parts) != 2:
                    print("Usage: /to <clientId> <message>")
                    continue
                target, message = parts
                await client.send(target, message)
                print(f"➡️   Sent to {target}")
                continue

            if line.startswith("/broadcast "):
                message = line[11:]
                await client.send("broadcast", message)
                print("➡️   Broadcast sent")
                continue

            print(f"Unknown command: {line}")

    try:
        await stdin_reader()
    except asyncio.CancelledError:
        pass
    finally:
        if client._running:
            await client.close()

    print("Goodbye!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
