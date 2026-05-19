# aitap Agent Coordination Protocol v1.0

Version: 1.0.0
Date: 2026-05-19
Relay: ws://localhost:3000 (or wss:// on deployed instances)

---

## Overview

This document defines the JSON message protocol used by Hermes and OpenClaw to coordinate ticket execution via the aitap WebSocket relay.

**Goal:** Replace Discord-based "Done, proceed?" babysitting with automated event-driven coordination.

**Principle:** One ticket at a time. No parallel processing. No merge conflicts.

---

## Connection

All agents connect to the same aitap relay:
```
ws://localhost:3000
```

Each agent receives a unique `clientId` from the relay welcome handshake.

| Agent | Client Name | Role |
|-------|-------------|------|
| Hermes | `hermes` | Receives completion events, decides next action |
| OpenClaw | `openclaw` | Sends completion events, receives proceed commands |

---

## Message Format

All messages are JSON with this envelope:

```json
{
  "target": "hermes",
  "payload": { ... }
}
```

The `payload` contains the actual event. The relay forwards based on `target`.

---

## Events

### 1. `ticket_done` — OpenClaw → Hermes

Sent when Ralph completes a ticket's dev phase.

```json
{
  "target": "hermes",
  "payload": {
    "event": "ticket_done",
    "ticket": "REMY-538",
    "phase": "dev",
    "branch": "feature/REMY-538-fixes",
    "commit": "abc1234",
    "timestamp": "2026-05-19T04:00:00Z"
  }
}
```

**Hermes action:**
1. Query Remy API for ticket REMY-538 status
2. Verify commit exists, tests pass
3. Determine next ticket in queue
4. Reply with `proceed` or `blocked`

---

### 2. `proceed` — Hermes → OpenClaw

Sent when Hermes approves moving to the next ticket.

```json
{
  "target": "openclaw",
  "payload": {
    "cmd": "proceed",
    "next_ticket": "REMY-539",
    "reason": "REMY-538 dev complete, no blockers",
    "timestamp": "2026-05-19T04:00:05Z"
  }
}
```

**OpenClaw action:**
1. Move REMY-538 to "In QA" status
2. Pick up REMY-539 from Dev Backlog
3. Start Ralph Setup phase for REMY-539

---

### 3. `blocked` — Hermes → OpenClaw

Sent when Hermes finds an issue that prevents proceeding.

```json
{
  "target": "openclaw",
  "payload": {
    "cmd": "blocked",
    "ticket": "REMY-538",
    "reason": "Tests failing on branch feature/REMY-538-fixes",
    "required_action": "Fix test failures and re-push",
    "timestamp": "2026-05-19T04:00:05Z"
  }
}
```

**OpenClaw action:**
1. Keep REMY-538 in current status
2. Alert user via Discord DM (fallback)
3. Wait for user intervention or `proceed` after fix

---

### 4. `status_check` — Hermes → OpenClaw (or any agent)

Sent when Hermes wants to know what OpenClaw is working on.

```json
{
  "target": "openclaw",
  "payload": {
    "cmd": "status_check",
    "timestamp": "2026-05-19T04:00:00Z"
  }
}
```

**OpenClaw action:**
Reply with `status_report` event.

---

### 5. `status_report` — OpenClaw → Hermes

```json
{
  "target": "hermes",
  "payload": {
    "event": "status_report",
    "current_ticket": "REMY-538",
    "current_phase": "dev",
    "phase_progress": "75%",
    "time_in_phase": "45 minutes",
    " Ralph_status": "building",
    "timestamp": "2026-05-19T04:00:00Z"
  }
}
```

---

## Fallback Behavior

If aitap relay is unreachable:

| Step | Action |
|------|--------|
| 1 | OpenClaw tries aitap 3 times with exponential backoff |
| 2 | After 3 failures, fall back to Discord `#openclaw-hermes` with `<@USER_ID>` mention |
| 3 | Hermes detects relay down via health check → also falls back to Discord |
| 4 | User (you) acts as manual bridge until relay recovers |

---

## Security Notes

- Both agents run on the same machine (Mac mini). Relay is localhost-only.
- No authentication needed for local relay (both are trusted processes).
- If relay is ever exposed externally, add HMAC signing to payloads.
- Version 1.0 assumes trusted network. Version 2.0 will add payload signatures.

---

## Example Flow

```
[OpenClaw] Ralph finishes REMY-538
  → aitap send: {event: "ticket_done", ticket: "REMY-538"}

[Relay] forwards to Hermes

[Hermes] receives message
  → checks Remy API: REMY-538 status = "In Dev"
  → checks git: commit abc1234 exists on branch
  → decides: proceed to REMY-539
  → aitap send: {cmd: "proceed", next_ticket: "REMY-539"}

[Relay] forwards to OpenClaw

[OpenClaw] receives proceed
  → moves REMY-538 to "In QA"
  → starts Ralph Setup for REMY-539
  → (45 min later) sends ticket_done for REMY-539
```

**Total human intervention:** Zero. Unless `blocked` event fires.

---

## Files

| File | Purpose |
|------|---------|
| `~/projects/aitap/PROTOCOL.md` | This document |
| `~/projects/aitap/clients/python/aitap_client.py` | Hermes Python client |
| `@thindery/aitap` npm package | OpenClaw Node.js client |
| `relay/server.js` | WebSocket relay (already running) |

---

## Changelog

- **v1.0.0 (2026-05-19):** Initial protocol. 5 event types. Local relay only.
