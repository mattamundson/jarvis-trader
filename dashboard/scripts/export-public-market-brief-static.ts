// @ts-nocheck -- executable Node --experimental-strip-types export helper; app code remains fully typechecked.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import { loadLivePublicMarketBrief } from "../lib/marketBrief/live.ts";
import { toPublicMarketBrief, type PublicScenario } from "../lib/marketBrief/public.ts";

function esc(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function pct(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}%` : "n/a";
}

function scenarioCard(scenario: PublicScenario): string {
  return `<section class="card scenario">
    <div class="eyebrow">Scenario</div>
    <h3>${esc(scenario.name)}</h3>
    <div class="probability">${pct(scenario.probability)}</div>
    <p>${esc(scenario.conditions.join(" "))}</p>
    <dl>
      <dt>Targets</dt><dd>${esc(scenario.targets.join(" · "))}</dd>
      <dt>Invalidation</dt><dd>${esc(scenario.invalidation)}</dd>
    </dl>
  </section>`;
}

function renderHtml(payload: ReturnType<typeof toPublicMarketBrief>): string {
  const probabilities = payload.scores.probabilities;
  const analysis = payload.analysis;
  const scenarios = analysis.scenarioMap.map(scenarioCard).join("\n");
  const generated = new Date(payload.generatedAt ?? Date.now()).toLocaleString("en-US", { timeZone: "America/Chicago", hour12: true });
  const list = (items: string[]) => `<ul>${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
  const structure = (label: string, structure: typeof analysis.esStructure) => `<section class="card"><h2>${esc(label)}</h2><p>${esc(structure.bias)}</p><dl><dt>Confirmation</dt><dd>${esc(structure.confirmation)}</dd><dt>Invalidation</dt><dd>${esc(structure.invalidation)}</dd><dt>Resistance</dt><dd>${esc(structure.resistance.join(" · "))}</dd><dt>Support</dt><dd>${esc(structure.support.join(" · "))}</dd></dl></section>`;
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>JARVIS Market Brief</title>
  <meta name="description" content="Read-only JARVIS Market Brief: analysis-only probabilities, scenario map, auction cues, and ES/NQ levels." />
  <style>
    :root { color-scheme: dark; --bg:#070b13; --card:#0f172a; --muted:#94a3b8; --text:#e5e7eb; --accent:#38bdf8; --border:#1f2937; --good:#22c55e; --warn:#f59e0b; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: radial-gradient(circle at top left, #172554 0, #070b13 34rem); color: var(--text); }
    main { max-width: 1180px; margin: 0 auto; padding: 32px 20px 56px; }
    .hero { border: 1px solid var(--border); background: rgba(15,23,42,.86); border-radius: 24px; padding: 28px; box-shadow: 0 24px 80px rgba(0,0,0,.35); }
    h1 { margin: 0 0 10px; font-size: clamp(2rem, 5vw, 4rem); line-height: .95; letter-spacing: -.05em; }
    h2 { margin: 0 0 14px; font-size: 1.35rem; }
    h3 { margin: 6px 0 8px; font-size: 1rem; }
    p { color: #cbd5e1; line-height: 1.65; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-top: 18px; }
    .grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .card { border: 1px solid var(--border); background: rgba(15,23,42,.9); border-radius: 18px; padding: 18px; }
    .prob { font-size: 2.35rem; font-weight: 800; letter-spacing: -.04em; color: var(--accent); }
    .probability { font-size: 2rem; font-weight: 800; color: var(--accent); }
    .eyebrow { color: var(--muted); text-transform: uppercase; font-size: .76rem; letter-spacing: .12em; font-weight: 700; }
    .badge { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--border); border-radius:999px; padding:7px 10px; margin: 4px 6px 4px 0; color:#dbeafe; background:rgba(59,130,246,.12); font-size:.85rem; }
    dl { display:grid; grid-template-columns: 110px 1fr; gap: 8px 12px; color:#cbd5e1; }
    dt { color: var(--muted); }
    dd { margin:0; }
    footer { margin-top: 22px; color: var(--muted); font-size: .86rem; }
    a { color: #7dd3fc; }
    @media (max-width: 820px) { .grid, .grid.two { grid-template-columns: 1fr; } .hero { padding: 20px; } }
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="eyebrow">JARVIS Market Brief · ${esc(payload.mode)} · ${esc(payload.sourceQuality)}</div>
      <h1>JARVIS Market Brief</h1>
      ${list(analysis.marketOverview)}
      <div>
        <span class="badge">BASE RATE</span>
        <span class="badge">NO MEASURED CONDITIONAL EDGE</span>
        <span class="badge">Generated ${esc(generated)} CT</span>
      </div>
      <div class="grid">
        <section class="card"><div class="eyebrow">Continuation</div><div class="prob">${pct(probabilities.continuation)}</div></section>
        <section class="card"><div class="eyebrow">Rotation</div><div class="prob">${pct(probabilities.rotation)}</div></section>
        <section class="card"><div class="eyebrow">Failure</div><div class="prob">${pct(probabilities.failure)}</div></section>
      </div>
    </section>

    <div class="grid two">
      <section class="card"><h2>Auction Market Theory Cues</h2>${list(analysis.auctionCues)}</section>
      <section class="card"><h2>Volatility Regime</h2>${list(analysis.volatilityRegime)}</section>
      ${structure("ES Structural Levels", analysis.esStructure)}
      ${structure("NQ Structural Levels", analysis.nqStructure)}
    </div>

    <section class="card" style="margin-top:16px"><h2>Scenario Map</h2><div class="grid">${scenarios}</div></section>
    <section class="card" style="margin-top:16px"><h2>Intraday Behavior Expectation</h2>${list(analysis.intradayPlan)}</section>
    <section class="card" style="margin-top:16px"><h2>Final Thoughts</h2>${list(analysis.finalThoughts)}</section>
    <section class="card" style="margin-top:16px"><h2>Public Safety Contract</h2><dl><dt>Trading controls</dt><dd>${esc(String(payload.publicContract.tradingControlsExposed))}</dd><dt>Local paths</dt><dd>${esc(String(payload.publicContract.localPathExposed))}</dd><dt>Orders enabled</dt><dd>${esc(String(payload.orders_enabled))}</dd><dt>Risk touched</dt><dd>${esc(String(payload.risk_config_touched))}</dd></dl></section>
    <footer>Static public artifact. JSON: <a href="../api/public-market-brief/latest.json">latest.json</a>. This is decision support only, not investment advice or an execution system.</footer>
  </main>
</body>
</html>`;
}

async function main() {
  const outDir = process.argv[2] ? path.resolve(process.argv[2]) : path.resolve("out-public-market-brief");
  const snapshot = await loadLivePublicMarketBrief();
  const payload = toPublicMarketBrief(snapshot);
  const html = renderHtml(payload);
  const json = `${JSON.stringify(payload, null, 2)}\n`;
  await mkdir(path.join(outDir, "market-brief-public"), { recursive: true });
  await mkdir(path.join(outDir, "api", "public-market-brief"), { recursive: true });
  await writeFile(path.join(outDir, "index.html"), html, "utf8");
  await writeFile(path.join(outDir, "market-brief-public", "index.html"), html, "utf8");
  await writeFile(path.join(outDir, "api", "public-market-brief", "latest.json"), json, "utf8");
  console.log(JSON.stringify({ outDir, generatedAt: payload.generatedAt, sourceQuality: payload.sourceQuality, mode: payload.mode, modelVersion: payload.modelVersion }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
