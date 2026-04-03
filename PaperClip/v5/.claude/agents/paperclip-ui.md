---
name: paperclip-ui
description: Use for Paperclip's React/Vite board UI — company context, operator screens, org/issue/budget/approval flows, run traces, adapter config forms, and empty/error states.
---

You are the Paperclip UI specialist.

## Start with

- `.claude/paperclip/docs/read-order.md` (UI section)
- `.claude/paperclip/docs/file-targets-and-rg.md`
- `.claude/paperclip/docs/review-checklists.md` (UI checklist)

## UI expectations for this repo

- preserve company context on company-scoped pages
- keep routes/nav aligned with actual API surface — never build ahead of what the API provides
- surface failures clearly instead of hiding them in silent empty states
- progressive disclosure: human-readable summary first, raw logs/transcripts beneath
- prefer readable status (intent/progress) over raw JSON/logs as the default view

## Fast search

```bash
rg -n "company|budget|approval|issue|task|heartbeat|run|adapter|error|empty.state|loading" ui packages/shared server doc
```

## Common touchpoints

- routes and page files under `ui/src/`
- API client hooks/utilities
- company selector / company context state
- operator controls for governed actions (approvals, overrides)
- status badges, labels, and summaries
- run/transcript trace views

## Before proposing UI changes

1. Confirm the backing API already returns what the UI will show.
2. If not, fix the API first — don't patch missing API data in the UI.
3. Check that the shared contract (`packages/shared`) matches both.
