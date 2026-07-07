Work on an adapter in paperclipai/paperclip.

Read `.claude/paperclip/docs/read-order.md` (Adapter section) and `.claude/paperclip/docs/review-checklists.md`.

For this adapter task:
1. Identify the adapter package (under `packages/adapters/`)
2. Map the change across: config shape, heartbeat integration, server integration, UI surfaces, CLI integration
3. Preserve runtime agnosticism — Paperclip orchestrates, not executes
4. Check `packages/adapter-utils/` for shared helpers to reuse

$ARGUMENTS
