import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/** Pin the actual tape API to synthetic files for BOTH CI and focused E2E. */
export function tapeFixtureEnv(): Record<string, string> {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'jarvis-tape-fixture-'));
  const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'tape-idle-market-closed-20261107.json'), 'utf8'));
  const raw = { ...fixture.snapshot,
    recorder: {state: 'idle (fixture)', heartbeat_age_s: 2, last_tick_age_s: null},
    session: {trading_day: '2026-11-07'}, levels_source: 'tape-plan dated 2026-11-03'};
  for (const [file, data] of Object.entries({'flow.json': raw, 'flow-latest.json': raw, 'plan.json': fixture.plan, 'gex.json': fixture.gex, 'gex-latest.json': fixture.gex})) {
    fs.writeFileSync(path.join(dir, file), JSON.stringify(data));
  }
  return {
    TAPE_FLOW_FILE: path.join(dir, 'flow.json'), TAPE_FLOW_FALLBACK_FILE: path.join(dir, 'flow.json'),
    TAPE_GEX_FILE: path.join(dir, 'gex.json'), TAPE_GEX_FALLBACK_FILE: path.join(dir, 'gex.json'),
    TAPE_PLAN_FILE: path.join(dir, 'plan.json'),
    TAPE_STATE_DIR: dir, TAPE_TICK_DIR: dir,
    TAPE_PROOF_FILE: path.join(dir, 'absent-proof.json'),
  };
}
