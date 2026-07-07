Trace a data or request path through paperclipai/paperclip.

Read `.claude/paperclip/docs/file-targets-and-rg.md` for search patterns.

For the entity or request described below:
1. Start from the API layer (route in `server/`)
2. Trace through shared contract (`packages/shared`)
3. Trace through DB layer (`packages/db`)
4. Identify UI consumption (`ui/`)
5. Note any adapter or plugin touchpoints
6. Call out company-scope enforcement at each layer

Use `rg` patterns from `file-targets-and-rg.md` to locate files rather than guessing.

$ARGUMENTS
