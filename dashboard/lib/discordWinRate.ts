// Win-rate percentage helper for Discord bot-signal widgets.
//
// WHY: `/discord/stats`'s `signals_by_symbol[].avg_win_rate` is
// `AVG(win_rate)` over `discord_bot_signals.win_rate`, which is stored
// on a 0-100 scale already (see engine/discord/signal_context.py's
// header comment: "The discord_bot_signals table stores win_rate as a
// percentage (0-100), not a ratio (0.0-1.0)"). Multiplying that value by
// 100 again is a double percentage-conversion bug (GT-07): every symbol
// rendered as 100% (real spread 66-82%), and a real 76.63 value would
// render as "7663.0%". This is the single point of truth for turning
// `avg_win_rate` into a display-ready percent -- don't re-multiply at
// the call site.
export function winRatePercent(
  avgWinRate: number | null | undefined,
): number {
  if (avgWinRate == null || Number.isNaN(avgWinRate)) return 0;
  return avgWinRate;
}
