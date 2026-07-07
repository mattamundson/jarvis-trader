/**
 * Single shared ATR-based position-sizing formula.
 *
 * Replaces two independently-drifting client implementations
 * (PositionSizerWidget's hardcoded MES constants, PositionSizingWidget's
 * hardcoded $10K account) that could legitimately disagree on the same
 * account+ATR inputs. All contract-count math for client-side widgets
 * should go through this module so risk % / stop multiplier / account
 * value assumptions can never silently diverge again.
 */

export interface AtrPositionSizeInputs {
  atr: number;
  accountValue: number;
  riskPct: number;
  atrStopMultiplier: number;
  atrTargetMultiplier: number;
  maxContracts: number;
  tickValue: number;
  ticksPerPoint: number;
}

export interface AtrPositionSizeResult {
  atrTicks: number;
  stopTicks: number;
  targetTicks: number;
  stopDollar: number;
  targetDollar: number;
  riskPerContract: number;
  riskPerTrade: number;
  computedContracts: number;
  effectiveContracts: number;
}

export function calcAtrPositionSize(inputs: AtrPositionSizeInputs): AtrPositionSizeResult {
  const {
    atr,
    accountValue,
    riskPct,
    atrStopMultiplier,
    atrTargetMultiplier,
    maxContracts,
    tickValue,
    ticksPerPoint,
  } = inputs;

  const atrTicks = atr * ticksPerPoint;
  const stopTicks = Math.round(atr * atrStopMultiplier * ticksPerPoint * 10) / 10;
  const targetTicks = Math.round(atr * atrTargetMultiplier * ticksPerPoint * 10) / 10;
  const stopDollar = stopTicks * tickValue;
  const targetDollar = targetTicks * tickValue;
  const riskPerContract = stopTicks * tickValue;
  const riskPerTrade = accountValue * riskPct;
  const computedContracts = riskPerContract > 0 ? Math.floor(riskPerTrade / riskPerContract) : 0;
  const effectiveContracts = Math.min(computedContracts, maxContracts);

  return {
    atrTicks,
    stopTicks,
    targetTicks,
    stopDollar,
    targetDollar,
    riskPerContract,
    riskPerTrade,
    computedContracts,
    effectiveContracts,
  };
}
