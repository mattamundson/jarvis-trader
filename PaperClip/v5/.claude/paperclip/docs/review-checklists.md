# Review checklists

Use before declaring work complete.

## Universal checklist

- [ ] Change respects company boundaries
- [ ] Intended package/layer boundaries identified correctly
- [ ] No core control-plane invariant weakened accidentally
- [ ] Error handling is explicit rather than silent
- [ ] Docs updated if behavior or commands changed

## DB / schema checklist

- [ ] Schema updated and exported
- [ ] Migration implications handled (`pnpm db:generate`)
- [ ] Shared types/validators/constants updated
- [ ] Server read/write logic updated
- [ ] UI consumer assumptions updated
- [ ] Database mode implications considered (embedded PGlite vs. hosted Postgres)

## API / server checklist

- [ ] Company scope enforced
- [ ] Shared request/response contracts updated
- [ ] Mutating behavior checked for: activity logging, approval gates, budget interactions
- [ ] Auth actors correct (board session vs. agent API key vs. agent run token)
- [ ] UI consumers updated
- [ ] Clear error behavior preserved

## UI checklist

- [ ] Routes/nav match actual API capability
- [ ] Company context preserved on company-scoped pages
- [ ] Empty/error/loading states are reasonable
- [ ] No contract drift papered over in the UI
- [ ] Progressive disclosure: summary first, drill-down second

## Adapter checklist

- [ ] Config shape remains coherent
- [ ] Invocation / heartbeat semantics still make sense
- [ ] Server integration points updated
- [ ] Status/config UI accurate
- [ ] Docs/examples reflect updated adapter behavior

## Plugin checklist

- [ ] Plugin behavior compatible with host expectations
- [ ] Workspace/path behavior correct
- [ ] SDK or example usage still accurate
- [ ] User-facing docs/examples updated if needed

## Release / packaging checklist

- [ ] `pnpm install && pnpm dev` still works on a fresh checkout
- [ ] Build passes
- [ ] Typecheck passes
- [ ] Relevant tests pass
- [ ] Release-critical paths smoke-tested
- [ ] Docs/command references accurate

## Final done check

- [ ] Behavior matches intent
- [ ] `pnpm build` passes
- [ ] `pnpm typecheck` passes
- [ ] Tests pass
- [ ] Contracts synchronized: db / shared / server / ui
- [ ] Changed commands or workflows documented
