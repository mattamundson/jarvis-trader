# gstack Skills — Routing Guide

gstack v0.15.1.0 is vendored at `.claude/skills/gstack/`. 33 specialized engineering skills.

**First-time setup** (requires Bun v1.0+):
```bash
cd .claude/skills/gstack && ./setup
```

## Skill → Workflow Routing

| Skill | When to Invoke |
|-------|----------------|
| `/review` | **Required** before any PR touching `engine/risk/safety_layer.py` |
| `/investigate` | Debug agent pipeline failures, unexpected behavior |
| `/qa` | Browser QA the dashboard at http://localhost:3010 |
| `/ship` | Full release: tests → review → push → PR |
| `/cso` | OWASP + STRIDE security audit of FastAPI engine |
| `/benchmark` | Pipeline latency regression detection |
| `/office-hours` | Product reframe before designing new trading features |

When the user asks to "review", "QA", "ship", or "investigate", proactively invoke the matching gstack skill.

**Browse binary**: `/qa` uses `.claude/skills/gstack/browse/dist/browse`. Run `./setup` to build.
