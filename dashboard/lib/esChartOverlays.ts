import { fetchEngine } from "./api";

export interface GammaLevels {
  netGex: number;
  gexFlipLevel: number;
  flowSignal: "BULLISH" | "BEARISH" | "NEUTRAL";
  pullTime: string;
}

export interface PlanLevels {
  entry: number | null;
  stop: number | null;
  target: number | null;
  symbol: string | null;
  direction: string | null;
  pullTime: string;
}

export interface ESOverlayData {
  gamma: GammaLevels | null;
  plan: PlanLevels | null;
}

interface RegimeResponse {
  price: number;
  options_flow: {
    flow_signal: "BULLISH" | "BEARISH" | "NEUTRAL";
    net_gex: number;
    gex_flip_level: number;
  } | null;
  updated_at: string;
}

interface PipelineStatusResponse {
  last_run?: {
    symbol?: string;
    direction?: string;
    entry?: number;
    stop?: number;
    target?: number;
    created_at?: string;
    [key: string]: unknown;
  } | null;
  recommendation?: {
    symbol?: string;
    direction?: string;
    entry?: number;
    stop?: number;
    target?: number;
    created_at?: string;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
}

export async function fetchESOverlayData(): Promise<ESOverlayData> {
  const [gammaResult, planResult] = await Promise.allSettled([
    fetchGammaLevels(),
    fetchPlanLevels(),
  ]);

  return {
    gamma: gammaResult.status === "fulfilled" ? gammaResult.value : null,
    plan: planResult.status === "fulfilled" ? planResult.value : null,
  };
}

async function fetchGammaLevels(): Promise<GammaLevels | null> {
  try {
    const data = await fetchEngine<RegimeResponse>("/regime/intraday?symbol=ES&futures=true");
    
    if (!data.options_flow) {
      return null;
    }

    return {
      netGex: data.options_flow.net_gex,
      gexFlipLevel: data.options_flow.gex_flip_level,
      flowSignal: data.options_flow.flow_signal,
      pullTime: data.updated_at,
    };
  } catch (error) {
    console.warn("Failed to fetch gamma levels:", error);
    return null;
  }
}

async function fetchPlanLevels(): Promise<PlanLevels | null> {
  try {
    const data = await fetchEngine<PipelineStatusResponse>("/pipeline/status");
    
    const rec = data.recommendation || data.last_run;
    if (!rec) {
      return null;
    }

    return {
      entry: typeof rec.entry === "number" ? rec.entry : null,
      stop: typeof rec.stop === "number" ? rec.stop : null,
      target: typeof rec.target === "number" ? rec.target : null,
      symbol: typeof rec.symbol === "string" ? rec.symbol : null,
      direction: typeof rec.direction === "string" ? rec.direction : null,
      pullTime: typeof rec.created_at === "string" ? rec.created_at : new Date().toISOString(),
    };
  } catch (error) {
    console.warn("Failed to fetch plan levels:", error);
    return null;
  }
}

export function isGammaStale(pullTime: string): boolean {
  const age = Date.now() - new Date(pullTime).getTime();
  return age > 60 * 60 * 1000;
}

export function formatAge(pullTime: string): string {
  const ageMs = Date.now() - new Date(pullTime).getTime();
  const ageMin = Math.floor(ageMs / 60000);
  
  if (ageMin < 60) {
    return `${ageMin}m`;
  }
  
  const ageHr = Math.floor(ageMin / 60);
  const remainMin = ageMin % 60;
  return `${ageHr}h${remainMin}m`;
}
