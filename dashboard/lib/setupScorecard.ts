export interface SetupRecord {
  date: string;
  setup_type: string;
  direction: "long" | "short";
  entry: number;
  stop: number;
  targets: number[];
  exit: number;
  outcome: "win" | "loss" | "breakeven";
  r: number;
  mfe: number;
  mae: number;
  time_of_day?: "premarket" | "open" | "midday" | "close" | "afterhours";
}

export interface SetupStats {
  total: number;
  wins: number;
  losses: number;
  breakeven: number;
  hit_rate: number;
  avg_r: number;
  expectancy: number;
  avg_mfe: number;
  avg_mae: number;
  best_r: number;
  worst_r: number;
}

export function computeSetupStats(records: SetupRecord[]): SetupStats {
  if (records.length === 0) {
    return {
      total: 0,
      wins: 0,
      losses: 0,
      breakeven: 0,
      hit_rate: 0,
      avg_r: 0,
      expectancy: 0,
      avg_mfe: 0,
      avg_mae: 0,
      best_r: 0,
      worst_r: 0,
    };
  }

  const wins = records.filter((r) => r.outcome === "win").length;
  const losses = records.filter((r) => r.outcome === "loss").length;
  const breakeven = records.filter((r) => r.outcome === "breakeven").length;
  const hit_rate = records.length > 0 ? (wins / records.length) * 100 : 0;
  
  const sum_r = records.reduce((acc, r) => acc + r.r, 0);
  const avg_r = sum_r / records.length;
  
  const sum_mfe = records.reduce((acc, r) => acc + r.mfe, 0);
  const avg_mfe = sum_mfe / records.length;
  
  const sum_mae = records.reduce((acc, r) => acc + r.mae, 0);
  const avg_mae = sum_mae / records.length;
  
  const expectancy = avg_r;
  const best_r = Math.max(...records.map((r) => r.r));
  const worst_r = Math.min(...records.map((r) => r.r));

  return {
    total: records.length,
    wins,
    losses,
    breakeven,
    hit_rate,
    avg_r,
    expectancy,
    avg_mfe,
    avg_mae,
    best_r,
    worst_r,
  };
}

export function groupBySetupType(records: SetupRecord[]): Map<string, SetupRecord[]> {
  const groups = new Map<string, SetupRecord[]>();
  for (const record of records) {
    const key = record.setup_type;
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(record);
  }
  return groups;
}

export function groupByTimeOfDay(records: SetupRecord[]): Map<string, SetupRecord[]> {
  const groups = new Map<string, SetupRecord[]>();
  for (const record of records) {
    const key = record.time_of_day ?? "unknown";
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(record);
  }
  return groups;
}

export const SAMPLE_SETUPS: SetupRecord[] = [
  {
    date: "2026-10-01",
    setup_type: "breakout",
    direction: "long",
    entry: 5750,
    stop: 5740,
    targets: [5765, 5780],
    exit: 5765,
    outcome: "win",
    r: 1.5,
    mfe: 2.1,
    mae: -0.3,
    time_of_day: "open",
  },
  {
    date: "2026-10-02",
    setup_type: "pullback",
    direction: "long",
    entry: 5755,
    stop: 5745,
    targets: [5770, 5785],
    exit: 5743,
    outcome: "loss",
    r: -1.0,
    mfe: 0.4,
    mae: -1.2,
    time_of_day: "midday",
  },
  {
    date: "2026-10-03",
    setup_type: "reversal",
    direction: "short",
    entry: 5770,
    stop: 5780,
    targets: [5755, 5740],
    exit: 5755,
    outcome: "win",
    r: 1.5,
    mfe: 2.0,
    mae: -0.5,
    time_of_day: "close",
  },
  {
    date: "2026-10-04",
    setup_type: "breakout",
    direction: "long",
    entry: 5760,
    stop: 5750,
    targets: [5775, 5790],
    exit: 5775,
    outcome: "win",
    r: 1.5,
    mfe: 1.8,
    mae: -0.2,
    time_of_day: "open",
  },
  {
    date: "2026-10-05",
    setup_type: "pullback",
    direction: "long",
    entry: 5765,
    stop: 5755,
    targets: [5780, 5795],
    exit: 5754,
    outcome: "loss",
    r: -1.0,
    mfe: 0.3,
    mae: -1.1,
    time_of_day: "midday",
  },
  {
    date: "2026-10-06",
    setup_type: "breakout",
    direction: "short",
    entry: 5780,
    stop: 5790,
    targets: [5765, 5750],
    exit: 5765,
    outcome: "win",
    r: 1.5,
    mfe: 2.2,
    mae: -0.4,
    time_of_day: "open",
  },
  {
    date: "2026-10-07",
    setup_type: "reversal",
    direction: "long",
    entry: 5755,
    stop: 5745,
    targets: [5770, 5785],
    exit: 5770,
    outcome: "win",
    r: 1.5,
    mfe: 1.9,
    mae: -0.3,
    time_of_day: "close",
  },
  {
    date: "2026-10-08",
    setup_type: "pullback",
    direction: "short",
    entry: 5775,
    stop: 5785,
    targets: [5760, 5745],
    exit: 5787,
    outcome: "loss",
    r: -1.0,
    mfe: 0.2,
    mae: -1.2,
    time_of_day: "midday",
  },
];
