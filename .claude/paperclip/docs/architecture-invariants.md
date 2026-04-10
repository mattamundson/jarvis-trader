# Architecture invariants

These rules matter most when changing Paperclip. Check against them before declaring any work complete.

## 1. Company scope is non-negotiable

Every domain entity is scoped to a company.
Every route and service touching company-owned data must enforce that boundary.

Ask on every change:
- Is this object company-scoped?
- Is the route enforcing that scope?
- Could this leak or mutate another company's data?

## 2. Contracts must stay synchronized

If behavior or shape changes in one layer, check all layers:

- `packages/db`
- `packages/shared`
- `server`
- `ui`

Classic failure: schema updated, server updated, UI or shared validators forgotten.

## 3. Preserve core control-plane behavior

Do not casually break or weaken:

- single-assignee task model
- atomic issue checkout semantics (`in_progress` transition must be atomic)
- approval gates for governed actions (hires, CEO strategy, etc.)
- budget hard-stop auto-pause behavior
- activity logging for all mutating actions

## 4. Keep strategic and implementation docs aligned

Do not replace strategic docs wholesale unless explicitly asked.
Prefer additive or surgical updates.

When behavior changes:
- update command docs if commands changed
- update implementation docs if workflows changed
- keep `doc/GOAL.md`, `doc/PRODUCT.md`, `doc/SPEC-implementation.md` aligned

## 5. Plan documents belong in one place

New plan docs → `doc/plans/YYYY-MM-DD-slug.md`

## 6. UI expectations

The UI should:
- keep routes and nav aligned with the available API surface
- respect company selection context on company-scoped pages
- surface failures clearly instead of silently ignoring them
- prefer readable summary first, drill-down second (progressive disclosure)

## 7. Database change expectations

Schema changes are not isolated. Expect to validate:
- schema + exports
- migration implications
- shared types/validators
- route/service behavior
- UI assumptions
- database-mode implications if relevant (embedded PGlite vs. hosted Postgres)

## 8. Definition of done

A Paperclip change is done when:
1. Behavior matches intent
2. Build passes
3. Typecheck passes
4. Tests appropriate to scope pass
5. Contracts are synchronized across db/shared/server/ui
6. Changed commands or workflows are documented
