# Local PR Gate

Use `scripts/local-pr-gate.ps1` when GitHub Actions cannot start or when you
want local merge-readiness evidence before pushing a PR.

Default run from a PR branch:

```powershell
pwsh -NoProfile -File scripts\local-pr-gate.ps1 -PrNumber 745
```

Full run, including dashboard build, Playwright, and slow pytest:

```powershell
pwsh -NoProfile -File scripts\local-pr-gate.ps1 -Full -PrNumber 745
```

The script writes a timestamped report under `docs/ci-reports/` and exits
nonzero on failures. It does not restart the engine, edit `.env` files, place
orders, or merge PRs.

Worktree note: most JARVIS feature worktrees do not contain their own
`engine/.venv`. The gate first checks the worktree venv, then falls back to the
canonical engine venv at `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine`.
Override that fallback with `JARVIS_CANONICAL_ENGINE_ROOT` when needed.

Notes:

- Default `auto` scope chooses engine/dashboard checks from the diff vs
  `origin/master`.
- `-Scope all` forces both engine and dashboard standard checks.
- `-IncludeComponent` runs dashboard Vitest component tests.
- `-IncludeBuild` runs `pnpm run build` and the bundle budget check.
- `-IncludeE2E` runs Playwright.
- `-IncludeSlow` runs the slow pytest slice.
- Build and typecheck run sequentially because `next build` mutates `.next`.
- The local security scan reports filenames only for value-pattern hits; raw
  secret values are intentionally not printed.
