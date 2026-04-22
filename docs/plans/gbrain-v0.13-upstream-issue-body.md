# Draft upstream issue — gbrain v0.13.0

**Submit at:** https://github.com/garrytan/gbrain/issues/new

**Title:**
```
v0.13.0: fresh init fails with `column "link_source" does not exist`; `config set` silently no-ops
```

**Body (paste into GitHub issue):**

```markdown
## Bug 1 — Fresh init broken

On a clean machine with no prior brain, `gbrain init` fails with a Postgres error on v0.13.0:

```
column "link_source" does not exist
```

This prevents any new user from initializing a PGLite brain. Reproduces on Windows 11 with Bun installed from scratch. Not a schema-upgrade path issue — it's a fresh init.

**Workaround:** Pin to v0.12.3 (commit `013b348c28a9954191543e54d9be1d63e1559de1`) — that's the last known-stable release. Init + import + search all work clean on 0.12.3.

## Bug 2 — `gbrain config set` silently no-ops

Separate issue, surfaced during Bug 1 investigation:

```
$ gbrain config set database_path /tmp/trading-brain.pglite
OK

$ cat ~/.gbrain/config.json
{"engine":"pglite","database_path":"/home/user/.gbrain/brain.pglite"}  # unchanged!
```

The command reports success but doesn't persist the change. Direct-editing `~/.gbrain/config.json` is the only reliable way to change `database_path`.

## Bug 3 (related) — `gbrain init` overwrites config

When operating two brains on one machine, I discovered `gbrain init` unconditionally writes `~/.gbrain/config.json` pointing at whatever DB it just initialized, even if I'd pre-edited config to point elsewhere. Source: `src/commands/init.ts:106-118` (as of v0.12.3; not checked against v0.13.x).

Adding `--path <file>` works — `gbrain init --path /tmp/my-brain.pglite` initializes at that path AND updates config accordingly. But a bare `gbrain init` silently "reclaims" the default path as canonical.

Suggestion: make `gbrain init` without `--path` refuse to overwrite a non-default `database_path` in config. Or at least warn before doing so.

## Environment

- OS: Windows 11 Home 10.0.26200
- Bun: (version as installed)
- gbrain versions tested: 0.12.3 (working), 0.13.0 (broken init)
- Engine: PGLite (bundled)

Happy to provide more details / stack traces if useful.
```

---

## After filing

Once the issue is up, update:
1. `jarvis-trader/docs/plans/2026-04-19-post-session-next-steps.md` Phase C2 — mark done with issue link
2. `~/.claude/projects/C--windows-system32/memory/gbrain-dual-brain.md` — add the issue URL so future sessions know where upstream is tracking
