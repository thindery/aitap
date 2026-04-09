# AGENTS.md - aitap Project Context

## Project Overview

**aitap** is a peer-to-peer messaging CLI tool that establishes direct lines between AI agents (or humans). Think walkie-talkies for agents — no central server required for the actual chat.

## Architecture Overview

aitap is a **Node.js CLI application** with three modes:
- **P2P Mode**: Direct peer-to-peer messaging over WebSocket
- **Meeting Point**: Rendezvous server for agents to find each other
- **Relay Mode**: Traditional server-forwarded messaging (fallback)

### What This Repo DOES
- ✅ P2P WebSocket connections between agents
- ✅ mDNS discovery (same WiFi auto-find)
- ✅ Meeting Point server for cross-network discovery
- ✅ Message reliability (ACKs, retry, dedup)
- ✅ Offline message queuing

### What This Repo Does NOT Do
- ❌ End-to-end encryption (alpha, planned for v0.0.4+)
- ❌ Cryptographic identity verification (planned)
- ❌ Production-grade security (alpha release only)
- ❌ Web UI (CLI only)

## Tech Stack

### Core Technologies
- **Runtime**: Node.js
- **Language**: TypeScript
- **Transport**: WebSocket
- **Discovery**: mDNS (local network), Meeting Point (remote)
- **Packaging**: npm global CLI (`@thindery/aitap`)

### Key Dependencies
- `ws` — WebSocket library
- `bonjour-service` — mDNS discovery
- `commander` — CLI framework

## Project Structure

```
aitap/
├── src/
│   ├── cli.ts              # CLI entry point
│   ├── p2p.ts              # P2P connection handling
│   ├── meetingpoint.ts     # Meeting point server
│   ├── protocol.ts         # Message protocol
│   └── types.ts            # TypeScript definitions
├── docs/                   # Technical documentation
├── tests/                  # Test suite
├── package.json            # npm manifest
└── README.md               # User-facing documentation
```

## Environment Variables

None required. aitap is zero-config by design.

Optional flags:
- `--p2p` — Enable P2P mode
- `--meetingpoint=<url>` — Connect to custom meeting point
- `--port=<num>` — Custom port for P2P listener

## Workflow & Development Standards (CRITICAL)

### Branch Naming
- Feature branches: `feature/{TICKET}-{brief-description}`
- Example: `feature/REMY-XXX-encrypt-messages`

### Commit Messages
Format: `{TICKET}: {description}`

Example:
```
REMY-XXX: Add message deduplication

Implemented deduplication to prevent duplicate messages
during retry scenarios. Uses message ID + timestamp hash.

Changes:
- Added message ID generation
- Implemented dedup cache (5-min window)
- Added tests for retry edge cases
```

### Ticket Completion Checklist
1. **Get ticket**: Check remy-tracker for assigned work
2. **Branch**: `git checkout -b feature/REMY-XXX-desc`
3. **Develop**: Implement changes in this repo
4. **Test**: `npm test` and manual P2P test with two terminals
5. **Commit**: `git commit -m "REMY-XXX: Description"`
6. **Push**: `git push -u origin feature/REMY-XXX-desc`
7. **PR**: Create PR, reference ticket
8. **Merge**: Squash merge after review
9. **Update ticket**: `remy move REMY-XXX --to="Closed/Done"`

**Important**: Code here → `remy` commands work globally → Tickets tracked in remy-tracker

## Key Features

### P2P Messaging
- Direct WebSocket connections between peers
- Automatic discovery via mDNS (same network)
- Manual discovery via Meeting Point (different networks)

### Reliability
- ACK receipts for delivery confirmation
- Exponential backoff retry (1s, 2s, 4s)
- Deduplication to prevent duplicates
- Offline queuing with delivery on reconnect

### CLI Interface
```
aitap --p2p                    # Start P2P mode
aitap-meetingpoint             # Start meeting point server
/peers                         # List online peers
/to <id> <msg>                 # Send message
/reply <msg>                   # Reply to last sender
```

## Common Tasks

### Running Locally
```bash
# Terminal 1 - Start P2P
aitap --p2p

# Terminal 2 - Start P2P (same machine, test)
aitap --p2p
```

### Testing P2P
```bash
# In both terminals:
/peers                          # Should see each other
/to <other-id> hello           # Send test message
/reply hey back                # Reply
```

### Deploying Meeting Point
```bash
# Fly.io
fly launch
fly deploy

# Or run locally
aitap-meetingpoint
```

### Publishing to npm
```bash
npm version patch|minor|major
npm publish
```

## Related Documentation
- `README.md` — User-facing quick start and usage
- `docs/` — Technical deep-dive documentation
- `AUDIT-TECH-LEAD.md` — Security audit notes
- `1-COMMAND.md` — Single-command operations guide

## Security Notes (Alpha)

**Current state:**
- ✅ Message reliability
- ✅ Peer identification via Badges
- ⚠️ **No end-to-end encryption yet**
- ⚠️ **No cryptographic identity verification yet**

**Use case:** Trusted networks and demos only until v0.0.4+ hardening.
