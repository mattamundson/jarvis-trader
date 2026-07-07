---
name: paperclip-adapters
description: Use for built-in runtime integrations in paperclipai/paperclip — config shape, heartbeat execution, stdout parsing, diagnostics, transcript formatting, and adapter UI/CLI coordination.
---

You are the Paperclip adapters specialist.

## Start with

- `.claude/paperclip/docs/read-order.md` (Adapter section)
- `.claude/paperclip/docs/file-targets-and-rg.md`
- `.claude/paperclip/docs/review-checklists.md` (Adapter checklist)
- `doc/PRODUCT.md` — adapter model section

## Adapter model

A real adapter change may span:
- `packages/adapters/<adapter>/src/index.ts`
- `packages/adapters/<adapter>/src/server/*`
- `packages/adapters/<adapter>/src/ui/*`
- `packages/adapters/<adapter>/src/cli/*`
- `packages/adapter-utils/*`
- server orchestration assumptions
- UI status/config surfaces

## Fast search

```bash
rg -n "adapterType|adapterConfig|execute\(|parse\(|format-event|heartbeat|wake|diagnostic|quota" packages/adapters packages/adapter-utils server ui doc
```

## Core principle to preserve

Paperclip orchestrates runtimes — it does not become the runtime.
The minimum adapter contract: be callable (process or HTTP).
Runtime agnosticism is a product guarantee.

## What to preserve in adapter changes

- clear config shape (adapter-specific, but documented)
- diagnosable failures (error surfaced to UI and logs)
- usage/cost extraction where applicable
- coherent behavior across server, UI, and CLI for the same adapter

## Built-in adapters

| Type | Description |
|------|-------------|
| `process` | Shell command / subprocess |
| `http` | Webhook / HTTP endpoint |
| Claude Code | `process` adapter targeting Claude CLI |
| Codex | `process` adapter targeting Codex |
| OpenClaw | `http` adapter with heartbeat wake-up |
| Cursor | `http` adapter |
