"""
ThinkScript Generator Agent
============================
Takes JARVIS TRADER analysis results and generates ThinkScript code
that can be pasted directly into ThinkorSwim charts.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ThinkScriptResult:
    symbol: str
    timeframe: str
    timestamp: datetime
    script_type: str  # "study", "strategy", "scan"
    title: str
    code: str
    description: str
    usage_instructions: str
    signals_included: list[str] = field(default_factory=list)


class ThinkScriptGeneratorAgent:
    """
    Generates ThinkScript code from JARVIS TRADER analysis.

    Produces ready-to-paste ThinkorSwim studies that visualize:
    - Support/resistance levels from technical analysis
    - Trend signals (EMA crossovers, momentum)
    - Bull/bear bias from the agent pipeline
    - Entry/exit zones based on confidence scores
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self._system_prompt = """You are an expert ThinkScript developer for ThinkorSwim.
Generate clean, well-commented ThinkScript code based on trading analysis.

ThinkScript syntax rules:
- Variables: `def varName = expression;`
- Plots: `plot plotName = expression;`
- Colors: `plotName.SetDefaultColor(Color.GREEN);`
- Arrows: `plotName.SetPaintingStrategy(PaintingStrategy.ARROW_UP);`
- Alerts: `Alert(condition, "message", Alert.BAR, Sound.Bell);`
- Bubbles: `AddChartBubble(condition, close, "text", Color.WHITE);`
- No semicolons after `if/then/else` blocks
- Use `IsNaN(close)` to guard against bad data
- `input` for user-configurable parameters

Always include:
1. A title comment block at the top
2. Input parameters users can tweak
3. Clear variable names
4. SetLineWeight and SetDefaultColor for all plots
5. An alert condition for the primary signal"""

    async def generate(
        self,
        symbol: str,
        timeframe: str = "15m",
        technical_report=None,
        pipeline_result: Optional[dict] = None,
        script_type: str = "study",
    ) -> ThinkScriptResult:
        """
        Generate ThinkScript code from analysis results.

        Args:
            symbol: Ticker symbol (e.g. "SPY", "MES")
            timeframe: Chart timeframe
            technical_report: TechnicalAnalystReport dataclass
            pipeline_result: Full pipeline result dict from TradingPipeline
            script_type: "study" (indicator), "strategy" (backtest), or "scan"
        """
        # Build context from available analysis
        analysis_context = self._build_context(symbol, timeframe, technical_report, pipeline_result)

        if self.llm_client:
            return await self._generate_with_llm(symbol, timeframe, script_type, analysis_context)
        else:
            return self._generate_template(
                symbol, timeframe, script_type, technical_report, pipeline_result
            )

    def _build_context(self, symbol, timeframe, technical_report, pipeline_result) -> str:
        parts = [f"Symbol: {symbol}", f"Timeframe: {timeframe}"]

        if technical_report:
            parts.extend(
                [
                    f"Signal: {getattr(technical_report, 'signal', 'N/A')}",
                    f"Trend: {getattr(technical_report, 'trend', 'N/A')}",
                    f"Regime: {getattr(technical_report, 'regime', 'N/A')}",
                    f"Trend Score: {getattr(technical_report, 'trend_score', 0):.2f}",
                    f"Momentum Score: {getattr(technical_report, 'momentum_score', 0):.2f}",
                    f"Current Price: {getattr(technical_report, 'current_price', 0)}",
                ]
            )
            support = getattr(technical_report, "support_levels", [])
            resistance = getattr(technical_report, "resistance_levels", [])
            if support:
                parts.append(f"Support Levels: {[f'{s:.2f}' for s in support[:3]]}")
            if resistance:
                parts.append(f"Resistance Levels: {[f'{r:.2f}' for r in resistance[:3]]}")

            indicators = getattr(technical_report, "indicators", {})
            if indicators:
                key_indicators = {
                    k: v
                    for k, v in indicators.items()
                    if k
                    in (
                        "ema_20",
                        "ema_50",
                        "rsi_14",
                        "macd",
                        "bb_upper",
                        "bb_lower",
                        "atr_14",
                        "vwap",
                    )
                }
                if key_indicators:
                    parts.append(f"Key Indicators: {key_indicators}")

        if pipeline_result:
            parts.extend(
                [
                    f"Final Action: {pipeline_result.get('final_action', 'hold')}",
                    f"Confidence: {pipeline_result.get('confidence', 0):.1%}",
                    f"Bull Score: {pipeline_result.get('bull_score', 0):.2f}",
                    f"Bear Score: {pipeline_result.get('bear_score', 0):.2f}",
                ]
            )

        return "\n".join(parts)

    async def _generate_with_llm(
        self, symbol, timeframe, script_type, analysis_context
    ) -> ThinkScriptResult:
        """Generate ThinkScript using Claude via JarvisLLMClient (with Gemini fallback)."""
        prompt = f"""Based on this JARVIS TRADER analysis, generate a ThinkScript {script_type} for ThinkorSwim:

{analysis_context}

Generate a complete, ready-to-paste ThinkScript {script_type} that:
1. Visualizes the key signals and levels from this analysis
2. Shows entry/exit zones based on the detected trend
3. Includes an alert for the primary signal
4. Has clear labels and colors (GREEN=bullish, RED=bearish, YELLOW=neutral)

Return ONLY the ThinkScript code — no explanation, no markdown fences, just raw ThinkScript."""

        try:
            result = await self.llm_client.call(
                model="claude-sonnet-4-6",
                system=self._system_prompt,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                agent_name="thinkscript_generator",
            )
            if not result.success:
                raise RuntimeError(f"LLM call failed: {result.error}")
            code = result.content.strip()
            # Strip markdown fences if present
            if code.startswith("```"):
                lines = code.split("\n")
                code = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            title = f"JARVIS {symbol} Analysis ({timeframe})"

            return ThinkScriptResult(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=datetime.now(),
                script_type=script_type,
                title=title,
                code=code,
                description=f"AI-generated ThinkScript study based on JARVIS TRADER analysis of {symbol}",
                usage_instructions=(
                    f"1. Open ThinkorSwim\n"
                    f"2. Go to Charts > Studies > Edit Studies\n"
                    f"3. Click 'Create' or paste into ThinkScript Editor\n"
                    f"4. Name it: '{title}'\n"
                    f"5. Click OK and apply to {symbol} {timeframe} chart"
                ),
                signals_included=["trend", "momentum", "support_resistance", "entry_zone"],
            )
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return self._generate_template(symbol, timeframe, script_type, None, None)

    def _generate_template(
        self, symbol, timeframe, script_type, technical_report, pipeline_result
    ) -> ThinkScriptResult:
        """Generate a solid template study when LLM is unavailable."""
        signal = "bullish"
        confidence = 0.5
        support = []
        resistance = []

        if technical_report:
            signal = getattr(technical_report, "signal", "neutral")
            support = getattr(technical_report, "support_levels", [])[:2]
            resistance = getattr(technical_report, "resistance_levels", [])[:2]
        if pipeline_result:
            confidence = pipeline_result.get("confidence", 0.5)
            signal = pipeline_result.get("final_action", signal)

        support_lines = (
            "\n".join(
                [
                    f"plot Support{i + 1} = {s:.2f};\nSupport{i + 1}.SetDefaultColor(Color.GREEN);\nSupport{i + 1}.SetLineWeight(2);"
                    for i, s in enumerate(support)
                ]
            )
            if support
            else "# No support levels detected"
        )

        resistance_lines = (
            "\n".join(
                [
                    f"plot Resistance{i + 1} = {r:.2f};\nResistance{i + 1}.SetDefaultColor(Color.RED);\nResistance{i + 1}.SetLineWeight(2);"
                    for i, r in enumerate(resistance)
                ]
            )
            if resistance
            else "# No resistance levels detected"
        )

        bias_color = (
            "Color.GREEN"
            if "buy" in signal.lower() or "bull" in signal.lower()
            else (
                "Color.RED"
                if "sell" in signal.lower() or "bear" in signal.lower()
                else "Color.YELLOW"
            )
        )

        code = f"""# ============================================================
# JARVIS TRADER — {symbol} Analysis Study
# Timeframe: {timeframe} | Signal: {signal.upper()} | Confidence: {confidence:.0%}
# Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
# ============================================================

input fastEMA = 20;
input slowEMA = 50;
input rsiLength = 14;
input rsiOverbought = 70;
input rsiOversold = 30;

# ── Trend EMAs ─────────────────────────────────────────────
def fastEMAVal = ExpAverage(close, fastEMA);
def slowEMAVal = ExpAverage(close, slowEMA);

plot FastLine = fastEMAVal;
FastLine.SetDefaultColor(Color.CYAN);
FastLine.SetLineWeight(2);

plot SlowLine = slowEMAVal;
SlowLine.SetDefaultColor(Color.ORANGE);
SlowLine.SetLineWeight(2);

# ── RSI ────────────────────────────────────────────────────
def rsiVal = RSI(length = rsiLength);
def rsiLong = rsiVal < rsiOversold;
def rsiShort = rsiVal > rsiOverbought;

# ── Trend Bias ─────────────────────────────────────────────
def bullTrend = fastEMAVal > slowEMAVal;
def bearTrend = fastEMAVal < slowEMAVal;

# JARVIS Bias Signal
def jarviBias = if bullTrend then 1 else if bearTrend then -1 else 0;

plot BiasArrowUp = if jarviBias == 1 and jarviBias[1] != 1 then low * 0.998 else Double.NaN;
BiasArrowUp.SetPaintingStrategy(PaintingStrategy.ARROW_UP);
BiasArrowUp.SetDefaultColor(Color.GREEN);
BiasArrowUp.SetLineWeight(3);

plot BiasArrowDown = if jarviBias == -1 and jarviBias[1] != -1 then high * 1.002 else Double.NaN;
BiasArrowDown.SetPaintingStrategy(PaintingStrategy.ARROW_DOWN);
BiasArrowDown.SetDefaultColor(Color.RED);
BiasArrowDown.SetLineWeight(3);

# ── Key Levels ─────────────────────────────────────────────
{support_lines}

{resistance_lines}

# ── Background Color ───────────────────────────────────────
AssignBackgroundColor(
    if bullTrend then Color.DARK_GREEN else
    if bearTrend then Color.DARK_RED else
    Color.DARK_GRAY
);

# ── Alerts ─────────────────────────────────────────────────
Alert(jarviBias == 1 and jarviBias[1] != 1, "JARVIS: Bullish crossover on {symbol}", Alert.BAR, Sound.Bell);
Alert(jarviBias == -1 and jarviBias[1] != -1, "JARVIS: Bearish crossover on {symbol}", Alert.BAR, Sound.Bell);

# ── Label ──────────────────────────────────────────────────
AddLabel(yes,
    "JARVIS: " + (if bullTrend then "BULLISH" else if bearTrend then "BEARISH" else "NEUTRAL") +
    " | RSI: " + Round(rsiVal, 1),
    {bias_color}
);
"""

        return ThinkScriptResult(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=datetime.now(),
            script_type=script_type,
            title=f"JARVIS {symbol} Analysis ({timeframe})",
            code=code,
            description=f"JARVIS TRADER study for {symbol} — shows trend EMAs, momentum signals, and key S/R levels",
            usage_instructions=(
                f"1. Open ThinkorSwim\n"
                f"2. Charts > Studies > Edit Studies > Create\n"
                f"3. Paste this code into the ThinkScript Editor\n"
                f"4. Name it: 'JARVIS {symbol} Analysis'\n"
                f"5. Click OK and apply to chart"
            ),
            signals_included=["ema_crossover", "rsi", "support_resistance", "trend_background"],
        )
