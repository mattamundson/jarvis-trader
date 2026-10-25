# TradingAgents structured-output schema note

**Purpose:** record the reusable patterns from `TradingAgents/tradingagents/agents/schemas.py` for possible adoption in JARVIS' own agent pipeline. Distilled from the schemas.py file only — the rest of TradingAgents (CLI, dataflows, LLM client factory, graph engine) is a divergent framework and is not being vendored.

---

## 1. Design pattern

TradingAgents layers structured Pydantic output onto prose-first agents so that:

- Outputs follow consistent section headers across runs and providers.
- Each provider's native structured-output mode is used (json_schema for OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic).
- **Schema field descriptions become the model's output instructions**, so the prompt body can focus on context and rating-scale guidance instead of restating field semantics.
- A render helper turns the parsed Pydantic instance back into the same markdown shape the rest of the system consumes — so display, memory log, and saved reports keep working unchanged.

This is a clean separation: schema = contract + output instructions; render = presentation.

---

## 2. Shared rating types

```python
class PortfolioRating(str, Enum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"

class TraderAction(str, Enum):
    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"
```

`PortfolioRating` is a 5-tier rating used by the Research Manager and Portfolio Manager. `TraderAction` is a 3-tier transaction direction (Buy/Hold/Sell) — the Trader's job is to translate the Research Manager's plan into a concrete transaction proposal; position sizing and the nuanced Overweight/Underweight calls happen later at the Portfolio Manager.

**JARVIS relevance:** JARVIS' own signal enums should follow the same pattern — separate the rating scale (directional conviction) from the action scale (execute/sit), and keep them in distinct models so the downstream router isn't conflating conviction with instruction.

---

## 3. ResearchPlan

```python
class ResearchPlan(BaseModel):
    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Choose Hold when the evidence is "
            "balanced, materially conflicting, ambiguous, or insufficient to "
            "justify changing exposure; otherwise commit to the side with the "
            "clearly stronger arguments. Do not pick a direction merely to be "
            "decisive."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "including position sizing guidance consistent with the rating."
        ),
    )
```

**JARVIS relevance:** the `Hold` guidance is the most reusable sentence — it explicitly encodes the decision rule for ambiguity ("Choose Hold when the evidence is balanced, materially conflicting, ambiguous, or insufficient"). JARVIS' own agent prompts should carry an equivalent rule so the model doesn't manufacture a direction just to be decisive.

---

## 4. TraderProposal

```python
class TraderProposal(BaseModel):
    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences."
        ),
    )
    entry_price: float | None = Field(
        default=None,
        description="Optional entry price target in the instrument's quote currency.",
    )
    stop_loss: float | None = Field(
        default=None,
        description="Optional stop-loss price in the instrument's quote currency.",
    )
    position_sizing: str | None = Field(
        default=None,
        description="Optional sizing guidance, e.g. '5% of portfolio'.",
    )

    @field_validator("entry_price", "stop_loss", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)
```

**JARVIS relevance:** the optional entry/stop/sizing fields with a nullish-coercion validator are exactly the shape JARVIS' pretrade signal schema should have — optional price levels, sized as strings (not hard floats) so the model can say "5% of portfolio" without inventing a fake number.

---

## 5. Nullish coercion helper

```python
_NULLISH_FLOAT = {"", "none", "n/a", "na", "null", "nil", "-", "tbd", "unknown"}

def _coerce_optional_float(value):
    if isinstance(value, str) and value.strip().lower() in _NULLISH_FLOAT:
        return None
    return value
```

LLMs sometimes write a placeholder string ("None", "N/A", "—", "tbd") into an optional numeric field instead of omitting it. This helper coerces those to `None` so the structured call validates instead of erroring. Pydantic still parses real numeric strings ("189.5") to float.

**JARVIS relevance:** this is a practical robustness patch JARVIS should adopt for any optional float field in an agent schema — it's the kind of thing that fails intermittently in production when a model decides to write "N/A" into an optional stop-loss field.

---

## 6. SentimentReport

```python
class SentimentReport(BaseModel):
    overall_band: SentimentBand = Field(...)
    overall_score: float = Field(
        ge=0, le=10,
        description=(
            "0–10 overall sentiment score. ... "
            "Guideline for consistency with overall_band: "
            "Bullish ~6.5–10, Mildly Bullish ~5.5–6.4, Neutral/Mixed ~4.5–5.5, "
            "Mildly Bearish ~3.5–4.4, Bearish ~0–3.4. "
            "Only the 0–10 bounds are enforced."
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description=(
            "Confidence in the assessment based on data quality and sample size. "
            "'low' when one or more sources returned a placeholder or fewer "
            "than 5 data points; 'medium' when data is present but sparse; "
            "'high' when all three sources returned substantive data."
        ),
    )
    narrative: str = Field(
        description=(
            "Full sentiment report covering, in order: "
            "(1) source-by-source breakdown with specific evidence; "
            "(2) cross-source divergences and alignments; "
            "(3) dominant narrative themes; "
            "(4) catalysts and risks surfaced by the data; "
            "(5) a markdown table summarising key sentiment signals. "
            "Keep it informative and substantive."
        ),
    )
```

**JARVIS relevance:** the `confidence` enum (low/medium/high) with an explicit data-quality rule is a useful pattern for JARVIS' own agent reports — it forces the model to say how much it trusts its own output, which is more useful than a bare score. The band/score pairing with a guideline (but only bounds enforced) is a pragmatic middle ground between rigid schema and free text.

---

## 7. Render helpers

```python
def render_research_plan(plan: ResearchPlan) -> str:
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])
```

Each model has a paired `render_*` function that turns the structured instance back into the markdown shape the rest of the system already consumes. This is what lets JARVIS store structured agent output in the journal and still display it as readable markdown without regex parsing.

**JARVIS relevance:** if JARVIS adopts structured agent output, it should pair every schema with a render helper so the journal and dashboard read the same markdown they always have — the structured layer is an internal contract, not a presentation change.

---

## 8. What NOT to vendor

TradingAgents is a 167-file multi-agent framework with its own CLI, dataflow adapters (Alpha Vantage, yfinance, FRED, Polymarket, Reddit, Stocktwits), LLM client factory (OpenAI, Anthropic, Gemini, Bedrock, OpenRouter, Ollama, DeepSeek, Minimax), graph engine, checkpointer, and reporting module. This note captures only the schemas.py patterns. The framework as a whole is a divergent architecture that would conflict with JARVIS' existing agent and dataflow design — it stays a reference fork.
