// Item 6: IB paper status light. Read-only checks only: a bare TCP probe of
// 127.0.0.1:4002 (no IB API handshake, no orders), process list, powercfg,
// IBC paper config TradingMode, and the engine's GET brokers/status.
import net from "net";
import fs from "fs/promises";
import { execFile } from "child_process";

const PORT = 4002;
let cached: { at: number; v: any } | null = null;

function run(cmd: string, args: string[]): Promise<string> {
  return new Promise((res) => execFile(cmd, args, { timeout: 8000, windowsHide: true }, (_e, out) => res(String(out ?? ""))));
}
function probe(port: number): Promise<boolean> {
  return new Promise((res) => {
    const s = net.connect({ host: "127.0.0.1", port });
    const done = (ok: boolean) => { s.destroy(); res(ok); };
    s.setTimeout(1500, () => done(false)); s.once("connect", () => done(true)); s.once("error", () => done(false));
  });
}

async function engineBroker(): Promise<any> {
  const base = process.env.ENGINE_INTERNAL_URL || process.env.ENGINE_URL_INTERNAL || "http://127.0.0.1:8010";
  const h: Record<string, string> = {}; if (process.env.ENGINE_API_KEY) h["X-API-Key"] = process.env.ENGINE_API_KEY;
  try { const r = await fetch(`${base}/brokers/status`, { headers: h, cache: "no-store", signal: AbortSignal.timeout(4000) }); return r.ok ? await r.json() : null; } catch { return null; }
}

function deep(o: any, key: string): any {
  if (!o || typeof o !== "object") return undefined;
  if (key in o) return o[key];
  for (const v of Object.values(o)) { const r = deep(v, key); if (r !== undefined) return r; }
  return undefined;
}

function findAccount(o: any): string | null {
  const s = JSON.stringify(o ?? {}); const m = s.match(/\b(DU|DF|U)\d{5,9}\b/); return m ? m[0] : null;
}

export async function readIbStatus() {
  if (cached && Date.now() - cached.at < 30_000) return cached.v;
  const [connected, tasks, pcfg, ini, broker] = await Promise.all([
    probe(PORT),
    run("tasklist", ["/FO", "CSV", "/NH"]),
    run("powercfg", ["/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"]),
    fs.readFile(process.env.IBC_PAPER_INI || "C:\\IBC\\config-paper.ini", "utf8").catch(() => ""),
    engineBroker(),
  ]);
  const gwCount = (tasks.match(/"ibgateway\d*\.exe"/gi) ?? []).length;
  const ac = pcfg.match(/Current AC Power Setting Index:\s*0x([0-9a-f]+)/i); const dc = pcfg.match(/Current DC Power Setting Index:\s*0x([0-9a-f]+)/i);
  const acS = ac ? parseInt(ac[1], 16) : null; const dcS = dc ? parseInt(dc[1], 16) : null;
  const mode = (ini.match(/^TradingMode=(\w+)/m) ?? [])[1] ?? null;
  const acct = findAccount(broker);
  const checks = [
    { name: "Port 4002 accepting (TCP probe)", ok: connected },
    { name: "Account starts with DU", ok: acct ? acct.startsWith("DU") : null, value: acct ? `${acct.slice(0, 2)}••••${acct.slice(-2)}` : "not exposed read-only" },
    { name: "IBC paper TradingMode", ok: mode === "paper", value: mode },
    { name: "Engine broker mode", ok: broker ? deep(broker, "mode") === "paper" && Number(deep(broker, "port")) === PORT : null, value: broker ? `${deep(broker, "mode") ?? "?"} :${deep(broker, "port") ?? "?"}` : "unavailable" },
    { name: "IB Gateway process up", ok: gwCount > 0, value: `${gwCount} ibgateway process(es)` },
    { name: "PC sleep disabled", ok: acS === 0 && dcS === 0 ? true : acS === null ? null : false, value: acS === null ? "unknown" : `AC ${acS ? acS / 60 + " min" : "never"} / DC ${dcS ? dcS / 60 + " min" : "never"}` },
  ];
  const hard = checks.filter((c) => c.ok === false).length;
  const unknown = checks.filter((c) => c.ok === null).length;
  const v = { ok: true, light: hard ? "red" : unknown ? "amber" : "green", checks, checkedAt: Date.now() };
  cached = { at: Date.now(), v };
  return v;
}
