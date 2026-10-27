/**
 * Pure parsers for Hermes's markdown / csv record files. Input is text, output is plain data.
 * No file access here (see read.ts) and no network. A field that cannot be found is `null`:
 * the page shows "not found in the record" instead of a guess.
 */

export type Row = Record<string, string>;

const clean = (s: string) => s.replace(/\*\*/g, "").replace(/`/g, "").replace(/\s+/g, " ").trim();
const num = (s: string) => Number(s.replace(/[−–]/g, "-").replace(/^\+/, ""));
const ISO = /\d{4}-\d{2}-\d{2}/;

function trunc(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s;
}

/** Split a markdown table line into trimmed cells (escaped pipes stay inside a cell). */
export function splitRow(line: string): string[] {
  const t = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return t.split(/(?<!\\)\|/).map((c) => c.replace(/\\\|/g, "|").trim());
}
const isSep = (line: string) => /^\s*\|?[\s:|-]+\|?\s*$/.test(line) && line.includes("-");

/** Lines of a "## <heading>" section (heading matched by prefix, case-insensitive). */
export function section(md: string, headingPrefix: string): string[] {
  const lines = md.split(/\r?\n/);
  const want = headingPrefix.toLowerCase();
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^##\s/.test(lines[i]) && lines[i].replace(/^##\s+/, "").toLowerCase().startsWith(want)) { start = i + 1; break; }
  }
  if (start < 0) return [];
  const out: string[] = [];
  for (let i = start; i < lines.length; i++) {
    if (/^##\s/.test(lines[i])) break;
    out.push(lines[i]);
  }
  return out;
}

/** Rows of the first table in `lines`, keyed by its header cells. */
export function tableRows(lines: string[]): Row[] {
  const rows: Row[] = [];
  let header: string[] | null = null;
  for (const line of lines) {
    if (!line.trim().startsWith("|")) { if (header && rows.length) break; continue; }
    if (isSep(line)) continue;
    const cells = splitRow(line);
    if (!header) { header = cells.map(clean); continue; }
    const r: Row = {};
    header.forEach((h, i) => { r[h] = clean(cells[i] ?? ""); });
    rows.push(r);
  }
  return rows;
}

// ---------------------------------------------------------------- ladder

export interface Ladder {
  step: string | null;
  cleanSessions: { done: number; target: number } | null;
  runningClean: { n: number; of: number } | null;
  scored: { n: number; of: number; avgR: number | null } | null;
  strikes30d: number | null;
  lockoutText: string | null;
  liveStatus: string | null;
  sessionLogThrough: string | null;
}

export interface SessionRow { date: string; bias: string; ruleBreaks: string; verdict: "clean" | "not clean" | "unknown"; note: string }
export interface UnlockItem { done: boolean; text: string }

export interface LadderBundle {
  ladder: Ladder;
  recentSessions: SessionRow[];
  sessionCount: number;
  unlock: UnlockItem[];
}

export function parseLadder(md: string): LadderBundle {
  const state = new Map<string, string>();
  for (const r of tableRows(section(md, "Current state"))) {
    const k = (r["Field"] ?? "").toLowerCase();
    if (k) state.set(k, r["Value"] ?? "");
  }
  const find = (prefix: string) => {
    for (const [k, v] of state) if (k.startsWith(prefix)) return v;
    return null;
  };
  const frac = (s: string | null) => {
    const m = s?.match(/(\d+)\s*\/\s*(\d+)/);
    return m ? { a: Number(m[1]), b: Number(m[2]) } : null;
  };

  const cleanF = frac(find("clean paper sessions"));
  const runF = frac(find("running count"));
  const scoredRaw = find("scored paper setups");
  const sf = frac(scoredRaw);
  const avg = scoredRaw?.match(/avg R\s*=\s*([+\-−–]?\d+(?:\.\d+)?)/i);
  const strikesRaw = find("strikes");
  const strikeN = strikesRaw?.match(/(\d+)\s+confirmed/i);
  const lockRaw = find("lockout");
  const liveRaw = find("live (any product");
  const logThrough = find("session log through")?.match(ISO);

  const rows = tableRows(section(md, "Session log"));
  const sessions: SessionRow[] = rows.filter((r) => ISO.test(r["Date"] ?? "")).map((r) => {
    const note = r["Notes"] ?? "";
    const verdict = /not clean/i.test(note) ? "not clean" : /\bclean\b/i.test(note) ? "clean" : "unknown";
    return { date: r["Date"], bias: trunc(r["Bias"] ?? "", 80), ruleBreaks: trunc(r["Rule breaks"] ?? "", 160), verdict, note: trunc(note, 200) } as SessionRow;
  });

  const unlock: UnlockItem[] = [];
  for (const line of section(md, "Unlock checklist")) {
    const m = line.match(/^\s*[-*]\s*\[( |x|X)\]\s*(.+)$/);
    if (m) unlock.push({ done: m[1].toLowerCase() === "x", text: trunc(clean(m[2]), 260) });
  }

  return {
    ladder: {
      step: find("step") ? trunc(clean(find("step")!), 220) : null,
      cleanSessions: cleanF ? { done: cleanF.a, target: cleanF.b } : null,
      runningClean: runF ? { n: runF.a, of: runF.b } : null,
      scored: sf ? { n: sf.a, of: sf.b, avgR: avg ? num(avg[1]) : null } : null,
      strikes30d: strikeN ? Number(strikeN[1]) : null,
      lockoutText: lockRaw ? trunc(clean(lockRaw), 260) : null,
      liveStatus: liveRaw ? trunc(clean(liveRaw), 200) : null,
      sessionLogThrough: logThrough ? logThrough[0] : null,
    },
    recentSessions: sessions.slice(-12).reverse(),
    sessionCount: sessions.length,
    unlock,
  };
}

// ---------------------------------------------------------------- strikes + lockout

export interface StrikeRow { id: string; date: string; logged: string; bans: string; status: string }
export interface StrikeLog {
  confirmed: StrikeRow[];
  pending: StrikeRow[];
  confirmedCount: number | null;
  countUpdated: string | null;
  countNote: string | null;
  window: { state: string; from: string; to: string } | null;
}

export function parseStrikeLog(md: string): StrikeLog {
  const confirmed = tableRows(section(md, "Confirmed strikes")).filter((r) => r["#"]).map((r) => ({
    id: r["#"], date: r["Date"] ?? "", logged: r["Logged"] ?? "",
    bans: trunc(r["Bans broken (from journal LIVE review rows)"] ?? "", 240), status: r["Confirmed by"] ?? "",
  }));
  const pending = tableRows(section(md, "Pending strikes")).filter((r) => ISO.test(r["Date"] ?? "")).map((r, i) => ({
    id: `P${i + 1}`, date: r["Date"], logged: r["Logged"] ?? "",
    bans: trunc(r["Bans broken (from journal LIVE review rows)"] ?? "", 240), status: r["Status"] ?? "",
  }));

  const countHeading = md.split(/\r?\n/).find((l) => /^##\s+Count/i.test(l)) ?? "";
  const countLines = section(md, "Count").map(clean);
  const conf = countLines.find((l) => /^[-*]?\s*Confirmed:/i.test(l))?.match(/Confirmed:\s*(\d+)/i);
  const note = countLines.find((l) => /^[-*]?\s*Confirmed:/i.test(l)) ?? null;
  const win = countLines.join(" ").match(/strike lockout:\s*(ACTIVE|ENDED|RELEASED)\s+(?:[A-Za-z]{3}\s+)?(\d{4}-\d{2}-\d{2})\s+through\s+(?:[A-Za-z]{3}\s+)?(\d{4}-\d{2}-\d{2})/i);

  return {
    confirmed, pending,
    confirmedCount: conf ? Number(conf[1]) : null,
    countUpdated: countHeading.match(ISO)?.[0] ?? null,
    countNote: note ? trunc(note.replace(/^[-*]\s*/, ""), 320) : null,
    window: win ? { state: win[1].toUpperCase(), from: win[2], to: win[3] } : null,
  };
}

export interface Condition { done: boolean; label: string; text: string }
export interface Lockout {
  /** ON unless the record shows it lifted; unknown is treated as ON. */
  on: boolean;
  strikeWindow: { from: string; to: string; phase: "before" | "in-window" | "after" } | null;
  weeklyUnreleased: boolean | null;
  releaseRecords: number | null;
  conditions: Condition[];
  summary: string;
}

/** CT calendar date (YYYY-MM-DD) for an instant, DST-aware. */
export function ctDate(now: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

export function parseLockout(strikes: StrikeLog | null, checklistMd: string | null, ladder: Ladder | null, now: Date): Lockout {
  const today = ctDate(now);
  const w = strikes?.window ?? null;
  const phase = w ? (today < w.from ? "before" : today > w.to ? "after" : "in-window") : null;

  const conditions: Condition[] = [];
  let releaseRecords: number | null = null;
  let weeklyUnreleased: boolean | null = null;
  if (checklistMd) {
    for (const line of section(checklistMd, "Conditions")) {
      const m = line.match(/^\s*[-*]\s*\[( |x|X)\]\s*(?:\*\*(.+?)\*\*:?)?\s*(.*)$/);
      if (m) conditions.push({ done: m[1].toLowerCase() === "x", label: clean(m[2] ?? ""), text: trunc(clean(m[3]), 260) });
    }
    const rec = tableRows(section(checklistMd, "Release record")).filter((r) => ISO.test(r["Date"] ?? ""));
    releaseRecords = rec.length;
    const weekly = /weekly 3R lockout from [^;\n]{0,40}?never released/i.test(checklistMd);
    weeklyUnreleased = weekly ? rec.length === 0 : null;
  }

  const ladderOn = ladder?.lockoutText ? /^\s*ON\b/i.test(ladder.lockoutText) : null;
  const anyOff = ladderOn === false && phase !== "in-window" && weeklyUnreleased === false;
  const on = !anyOff; // fail safe: unknown means ON

  let summary: string;
  if (phase === "in-window") summary = `5-day strike lockout ACTIVE ${w!.from} to ${w!.to} (CT).`;
  else if (phase === "after") summary = `Strike lockout window ended ${w!.to}; release still needs the checklist and Matt's written yes.`;
  else if (phase === "before") summary = `Strike lockout starts ${w!.from}.`;
  else summary = "Strike lockout window not found in the record; treated as ON.";
  if (weeklyUnreleased) summary += " Weekly 3R lockout (from 10/6) is still unreleased.";

  return { on, strikeWindow: w ? { from: w.from, to: w.to, phase: phase! } : null, weeklyUnreleased, releaseRecords, conditions, summary };
}

// ---------------------------------------------------------------- journal

export interface JournalEntry {
  date: string; session: string; bias: string; liveLegal: string; result: string; rResult: string; notes: string; live: boolean;
}
export interface Journal { total: number; liveReviews: number; recent: JournalEntry[]; lastDate: string | null }

export function parseJournal(md: string, limit = 14): Journal {
  const entries: JournalEntry[] = [];
  let header: string[] | null = null;
  for (const line of md.split(/\r?\n/)) {
    if (!line.trim().startsWith("|")) { if (line.trim() !== "") header = null; continue; }
    if (isSep(line)) continue;
    const cells = splitRow(line);
    if (/^date$/i.test(clean(cells[0] ?? "")) && cells.some((c) => /^session$/i.test(clean(c)))) { header = cells.map(clean); continue; }
    if (!header || !ISO.test(cells[0] ?? "")) continue;
    const get = (name: string) => { const i = header!.findIndex((h) => h.toLowerCase().startsWith(name)); return i >= 0 ? clean(cells[i] ?? "") : ""; };
    const session = get("session");
    entries.push({
      date: clean(cells[0]), session: trunc(session, 80), bias: trunc(get("bias"), 60), liveLegal: trunc(get("live legal"), 80),
      result: trunc(get("result"), 120), rResult: trunc(get("r result"), 80), notes: trunc(get("notes"), 360), live: /LIVE review/i.test(session),
    });
  }
  return {
    total: entries.length,
    liveReviews: entries.filter((e) => e.live).length,
    recent: entries.slice(-limit).reverse(),
    lastDate: entries.length ? entries[entries.length - 1].date : null,
  };
}

// ---------------------------------------------------------------- scored setups csv

export interface ScoredCsv { rows: number; avgR: number | null }

export function parseScoredCsv(text: string): ScoredCsv {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 1) return { rows: 0, avgR: null };
  const head = lines[0].split(",").map((h) => h.trim().toLowerCase());
  const ri = head.indexOf("r");
  const data = lines.slice(1);
  const rs = ri >= 0 ? data.map((l) => Number(l.split(",")[ri]?.replace(/[−–]/g, "-"))).filter((x) => Number.isFinite(x)) : [];
  return { rows: data.length, avgR: rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : null };
}
