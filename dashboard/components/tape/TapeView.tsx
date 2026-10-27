"use client";

import useSWR from "swr";
import { POLL_INTERVAL } from "@/lib/polling-config";
import { fetchTape } from "@/lib/tape/client";
import type { TapePayload } from "@/lib/tape/serialize";
import { FlowChart } from "./FlowChart";
import { useClockMs } from "./Fresh";
import { GateLevels, GatesFooter, GexSection, LegsTable, LevelSection, NqPanel, Panel, ReadoutTiles, StatusBar } from "./Panels";
import { C, MONO } from "./theme";

export function TapeView() {
  const { data, error } = useSWR<TapePayload>("/api/tape", fetchTape, {
    refreshInterval: POLL_INTERVAL.FAST,
    revalidateOnFocus: false,
    keepPreviousData: true,
  });
  const nowMs = useClockMs(data?.generated_ms);
  const flow = data?.flow.data ?? null;
  const price = flow?.price?.last ?? null;

  return (
    <div className="min-h-screen px-3 py-3" style={{ background: C.bg, color: C.text }} data-testid="tape-root">
      <div className="mx-auto grid max-w-[1800px] grid-cols-12 gap-2">
        <StatusBar payload={data} nowMs={nowMs} />
        {error && !data && (
          <div className={`col-span-12 border px-2 py-1 text-[10px] uppercase ${MONO}`} style={{ borderColor: C.red, color: C.red }}>
            Tape feed unreachable ({String(error.message ?? error)}). Showing nothing rather than guessing.
          </div>
        )}
        <Panel title="Order flow · CVD / price / legs / lots per min" className="col-span-12 xl:col-span-9" testId="panel-flow"
          right={<span className={`text-[9px] ${MONO}`} style={{ color: C.dim }}>1-min bars · CT</span>}>
          <FlowChart flow={flow} />
        </Panel>
        <div className="col-span-12 xl:col-span-3"><ReadoutTiles flow={flow} /></div>

        <div className="col-span-12 lg:col-span-4"><GateLevels flow={flow} /></div>
        <div className="col-span-12 lg:col-span-4"><LegsTable flow={flow} /></div>
        <div className="col-span-12 lg:col-span-4"><NqPanel flow={flow} nowMs={nowMs} /></div>

        {data && (
          <>
            <GexSection env={data.gex} price={price} nowMs={nowMs} />
            <LevelSection name="DoubleWide" env={data.doublewide} price={price} nowMs={nowMs} file="doublewide-latest.json" testId="src-dw" />
            <LevelSection name="Aaron" env={data.aaron} price={price} nowMs={nowMs} file="aaron-latest.json" testId="src-aaron" />
          </>
        )}
        <GatesFooter gates={data?.gates} />
      </div>
    </div>
  );
}
