"""Emit docs/strategy/STRATEGY_CANON_REVIEW.html from TRADING_RULES.md + EQUATIONS.md."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "docs" / "strategy" / "TRADING_RULES.md"
EQUATIONS = ROOT / "docs" / "strategy" / "EQUATIONS.md"
OUT = ROOT / "docs" / "strategy" / "STRATEGY_CANON_REVIEW.html"


def _latex_to_katex_fences(md: str) -> str:
    """Turn \\[ \\] and \\( \\) into $$ / $ so Showdown leaves math for KaTeX."""
    md = re.sub(r"\\\[(.*?)\\\]", r"\n$$\n\1\n$$\n", md, flags=re.DOTALL)
    md = re.sub(r"\\\((.*?)\\\)", r"$\1$", md, flags=re.DOTALL)
    return md


def main() -> None:
    rules = RULES.read_text(encoding="utf-8")
    equations = _latex_to_katex_fences(EQUATIONS.read_text(encoding="utf-8"))
    rules_j = json.dumps(rules, ensure_ascii=False)
    eq_j = json.dumps(equations, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>JARVIS TRADER — Strategy canon review</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" crossorigin="anonymous" />
  <style>
    :root {{
      --bg: #0c0e12;
      --panel: #141820;
      --border: #2a3140;
      --text: #e8eaef;
      --muted: #8b95a8;
      --accent: #3d9cf0;
      --accent-dim: #2563a8;
      --ok: #34d399;
      --warn: #fbbf24;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.55;
      font-size: 15px;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 20;
      background: linear-gradient(180deg, #0f1218 0%, rgba(12,14,18,0.96) 100%);
      border-bottom: 1px solid var(--border);
      padding: 0.75rem 1.25rem;
      backdrop-filter: blur(8px);
    }}
    header h1 {{
      margin: 0;
      font-size: 1.05rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--accent);
    }}
    header p {{
      margin: 0.25rem 0 0;
      font-size: 0.8rem;
      color: var(--muted);
    }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-top: 0.6rem;
    }}
    nav a {{
      font-family: "JetBrains Mono", monospace;
      font-size: 0.72rem;
      color: var(--accent);
      text-decoration: none;
      padding: 0.35rem 0.65rem;
      border: 1px solid var(--border);
      border-radius: 4px;
      background: var(--panel);
    }}
    nav a:hover {{ border-color: var(--accent-dim); color: #7ec8ff; }}
    main {{ max-width: 52rem; margin: 0 auto; padding: 1.5rem 1.25rem 4rem; }}
    section {{
      margin-bottom: 3rem;
      scroll-margin-top: 5.5rem;
    }}
    section h2 {{
      font-size: 1.15rem;
      font-weight: 700;
      border-left: 3px solid var(--accent);
      padding-left: 0.75rem;
      margin: 0 0 1rem;
      color: #fff;
    }}
    .prose {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem 1.35rem;
    }}
    .prose h1, .prose h2, .prose h3, .prose h4 {{
      margin-top: 1.35rem;
      margin-bottom: 0.5rem;
      color: #f0f2f6;
    }}
    .prose h1 {{ font-size: 1.25rem; }}
    .prose h2 {{ font-size: 1.1rem; border: none; padding: 0; }}
    .prose h3 {{ font-size: 1rem; color: var(--muted); }}
    .prose p {{ margin: 0.65rem 0; }}
    .prose ul, .prose ol {{ margin: 0.5rem 0; padding-left: 1.35rem; }}
    .prose li {{ margin: 0.35rem 0; }}
    .prose code {{
      font-family: "JetBrains Mono", monospace;
      font-size: 0.82em;
      background: #0a0c10;
      padding: 0.12em 0.35em;
      border-radius: 3px;
      border: 1px solid var(--border);
    }}
    .prose pre {{
      background: #0a0c10;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 1rem;
      overflow-x: auto;
      font-size: 0.78rem;
      line-height: 1.45;
    }}
    .prose pre code {{ background: none; border: none; padding: 0; }}
    .prose table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
      margin: 1rem 0;
    }}
    .prose th, .prose td {{
      border: 1px solid var(--border);
      padding: 0.45rem 0.55rem;
      text-align: left;
      vertical-align: top;
    }}
    .prose th {{ background: #1a1f2e; color: var(--ok); font-weight: 600; }}
    .prose tr:nth-child(even) td {{ background: rgba(0,0,0,0.15); }}
    .prose a {{ color: var(--accent); }}
    .prose hr {{ border: none; border-top: 1px solid var(--border); margin: 1.25rem 0; }}
    .prose blockquote {{
      margin: 0.75rem 0;
      padding-left: 1rem;
      border-left: 3px solid var(--warn);
      color: var(--muted);
    }}
    .katex-display {{ overflow-x: auto; overflow-y: hidden; padding: 0.35rem 0; }}
    footer {{
      text-align: center;
      padding: 2rem 1rem;
      color: var(--muted);
      font-size: 0.75rem;
      border-top: 1px solid var(--border);
    }}
  </style>
</head>
<body>
  <header>
    <h1>JARVIS TRADER — Strategy canon</h1>
    <p>Generated from <code>docs/strategy/TRADING_RULES.md</code> + <code>EQUATIONS.md</code> — open this file in a browser (online for math fonts).</p>
    <nav>
      <a href="#trading-rules">Trading rules</a>
      <a href="#equations">Equations</a>
    </nav>
  </header>
  <main>
    <section id="trading-rules">
      <h2>1. Trading rules &amp; thesis</h2>
      <div class="prose" id="rules-body"></div>
    </section>
    <section id="equations">
      <h2>2. Mathematics (equation reference)</h2>
      <div class="prose" id="equations-body"></div>
    </section>
  </main>
  <footer>
    Regenerate: <code>python scripts/build_strategy_review_html.py</code>
  </footer>
  <script src="https://cdn.jsdelivr.net/npm/showdown@2.1.0/dist/showdown.min.js" crossorigin="anonymous"></script>
  <script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js" crossorigin="anonymous"></script>
  <script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" crossorigin="anonymous"></script>
  <script>
    const RULES_MD = {rules_j};
    const EQUATIONS_MD = {eq_j};
    const conv = new showdown.Converter({{ tables: true, strikethrough: true, tasklists: true }});
    document.getElementById("rules-body").innerHTML = conv.makeHtml(RULES_MD);
    document.getElementById("equations-body").innerHTML = conv.makeHtml(EQUATIONS_MD);
    renderMathInElement(document.getElementById("equations-body"), {{
      delimiters: [
        {{ left: "$$", right: "$$", display: true }},
        {{ left: "$", right: "$", display: false }},
      ],
      throwOnError: false,
    }});
  </script>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
