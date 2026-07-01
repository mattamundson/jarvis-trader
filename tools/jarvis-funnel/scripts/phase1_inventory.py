"""
Phase 1 Inventory Pipeline
==========================

Walks the jarvis-trader repo + the OneDrive bookmark export and produces
strategies_v1.jsonl — the canonical strategy card list.

Designed to be run locally:
    python -m jarvis_funnel.phase1_inventory \
        --repo C:/path/to/jarvis-trader \
        --bookmarks "C:/Users/matt/OneDrive/jarvis-trader-handoff/bookmarks.html" \
        --out "C:/Users/matt/OneDrive/jarvis-trader-handoff/cards/strategies_v1.jsonl"

What it does:
1. Walks repo: extracts hypothesis atoms from engine/backtest/run_*.py,
   engine/strategies/, engine/strategy_lab/, *.pine TOS scripts, top-level *.md docs.
2. Parses bookmarks export: extracts hypothesis atoms from each bookmark.
3. Computes cross-source similarity (see references/bookmark_to_code_mapping.md).
4. Merges high-confidence matches, flags medium-confidence for review.
5. Writes strategies_v1.jsonl following references/strategy_card_schema.md.
6. Writes side artifacts: atoms_repo.jsonl, atoms_bookmarks.jsonl, merge_review.jsonl.

LLM usage: this script uses an LLM (default: Claude Sonnet via Anthropic API or
OpenAI GPT-4-class via OpenAI API) for the actual atom extraction. Configure via
env vars JARVIS_FUNNEL_LLM_PROVIDER and JARVIS_FUNNEL_LLM_MODEL. Hypothesis_id
generation is deterministic (no LLM), so atoms are reproducible.

Dependencies: python>=3.10, pydantic, beautifulsoup4 (for bookmark HTML),
anthropic OR openai (for LLM atom extraction).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis_funnel.phase1")

# Inventory script version — bumped when behavior changes that affects card output
INVENTORY_VERSION = "1.1"

# Noise tokens that should never appear in a hypothesis_id descriptor
_DESCRIPTOR_NOISE = {
    "run", "signals", "backtester", "wfo", "runner", "walk", "forward",
    "backtest", "fresh", "rank", "test", "v2", "v3", "generic",
    "the", "and", "for", "with", "when", "this", "that", "from",
    "all", "any", "after", "across", "absent", "actual", "add",
    "forward", "based", "using", "new",
}

# Instrument symbol → instrument_class mapping (canonical, single source of truth)
_INSTRUMENT_TO_CLASS = {
    # ES family
    "ES": "es", "MES": "es", "SPX": "es", "SPY": "es",
    # NQ family
    "NQ": "nq", "MNQ": "nq", "NDX": "nq", "QQQ": "nq",
    # RTY family
    "RTY": "rty", "M2K": "rty", "IWM": "rty",
    # Gold
    "GC": "gc", "MGC": "gc", "GLD": "gc",
    # Crude oil
    "CL": "cl", "MCL": "cl", "USO": "cl",
    # Corn
    "ZC": "zc",
    # Vol products
    "VIX": "vix", "VXX": "vix", "UVXY": "vix", "VVIX": "vix",
    # Crypto
    "BTC": "btc",
}

# ── Constants ────────────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "breakout": ["breakout", "orb", "opening range", "donchian", "channel break"],
    "mean_reversion": ["mean reversion", "meanrev", "rsi oversold", "bollinger", "vwap reversion", "ou process"],
    "trend_following": ["trend", "ema cross", "macd", "moving average", "adx"],
    "momentum": ["momentum", "rate of change", "roc", "relative strength"],
    "carry": ["carry", "contango", "backwardation", "roll yield"],
    "arbitrage": ["arbitrage", "spread", "pair trade", "stat arb"],
    "event_driven": ["earnings", "fomc", "nfp", "cpi", "event", "news"],
    "volatility": ["vix", "vol", "iv", "volatility", "vvix", "term structure"],
    "seasonality": ["seasonal", "tom", "turn of month", "day of week", "holiday"],
    "microstructure": ["tape", "order flow", "imbalance", "bid ask", "liquidity"],
    "ml_based": ["random forest", "neural", "rl", "reinforcement", "xgboost", "lstm"],
    "composite": ["composite", "ensemble", "vote", "confluence"],
}

INSTRUMENT_CLASSES = {
    "es": ["es", "mes", "spx", "spy", "es_f"],
    "nq": ["nq", "mnq", "ndx", "qqq"],
    "rty": ["rty", "m2k", "iwm"],
    "gc": ["gc", "mgc", "gold", "gld"],
    "cl": ["cl", "mcl", "wti", "oil", "uso"],
    "zc": ["zc", "corn"],
    "vix": ["vix", "vxx", "uvxy", "vvix"],
    "btc": ["btc", "bitcoin", "btc_usd"],
    "equity": ["spy", "qqq", "iwm", "tsla", "aapl", "single stock"],
    "options": ["option", "call", "put", "iv rank", "skew", "smile"],
}

TF_CLASSES = {
    "intraday": ["1m", "5m", "15m", "30m"],
    "swing": ["1h", "4h", "1d"],
    "overnight": ["overnight", "rth close to open", "globex"],
    "multiday": ["1d", "1w", "weekly", "multi-day"],
    "eod": ["eod", "end of day", "close"],
}


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class HypothesisAtom:
    """One unit of strategy info extracted from a single source file or bookmark."""

    source_type: str  # "repo_runner" | "repo_signal" | "repo_strategy" | "tos_script" | "analysis_doc" | "bookmark"
    source_path: str  # filesystem path OR bookmark URL
    source_metadata: dict  # git_sha, author_handle, saved_at, etc.

    category: Optional[str]
    subcategory: Optional[str]
    instrument_class: Optional[str]
    raw_instruments: list[str]
    timeframe_class: Optional[str]
    raw_timeframes: list[str]

    entry_keywords: list[str]
    exit_keywords: list[str]
    parameter_names: list[str]
    parameter_defaults: dict

    claimed_metrics: dict  # sharpe, win_rate, pf, etc. if stated
    economic_rationale_draft: str
    rationale_strength: str  # STRONG | MODERATE | WEAK | MISSING

    raw_text_sample: str  # first 500 chars for human review

    # v1.1 additions
    is_library: bool = False  # instrument-agnostic helper file (not a runnable strategy)
    category_ambiguous: bool = False  # top-2 category scores within 30% — flag for LLM tiebreak
    category_runners_up: list[str] = field(default_factory=list)  # alternative categories worth considering

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StrategyCard:
    """The merged, canonical strategy representation. Matches strategy_card_schema.md."""

    hypothesis_id: str
    schema_version: str = "1.0"
    created_at: str = ""
    updated_at: str = ""

    name: str = ""
    category: str = ""
    subcategory: str = ""

    economic_rationale: str = ""
    rationale_strength: str = "MISSING"

    instruments: dict = field(default_factory=lambda: {"primary": "", "tested_on": [], "applicable_to": [], "do_not_use_on": []})
    timeframes: dict = field(default_factory=lambda: {"primary": "", "applicable": [], "rationale_for_tf": ""})

    entry_logic: str = ""
    exit_logic: str = ""
    parameters: dict = field(default_factory=dict)
    parameter_sensitivity_to_test: dict = field(default_factory=dict)

    expected_regime_performance: dict = field(default_factory=dict)
    expected_failure_modes: list = field(default_factory=list)

    provenance: dict = field(default_factory=lambda: {"repo_sources": [], "bookmark_sources": [], "external_doc_sources": []})
    untested_variants_from_bookmarks: list = field(default_factory=list)

    implementation_status: dict = field(default_factory=lambda: {
        "exists_in_repo": False,
        "has_backtest": False,
        "has_walk_forward": False,
        "has_paper_trading": False,
        "has_live_trading": False,
        "current_repo_verdict": None,
    })

    phase_1_status: Optional[str] = None
    phase_2_status: Optional[str] = None
    phase_3_status: Optional[str] = None
    phase_4_status: Optional[str] = None

    current_tier: Optional[str] = None
    tier_history: list = field(default_factory=list)

    next_action: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Atom Extraction: Repo ────────────────────────────────────────────────────


def extract_repo_atoms(repo_path: Path, llm_extract_fn) -> list[HypothesisAtom]:
    """Walk the repo and extract a hypothesis atom per relevant file."""
    atoms: list[HypothesisAtom] = []

    # Strategy runners — the most reliable source
    runner_files = list((repo_path / "engine" / "backtest").glob("run_*.py"))
    signal_files = list((repo_path / "engine" / "backtest").glob("*_signals.py"))
    strategy_files = list((repo_path / "engine" / "strategies").glob("*.py"))
    lab_files = list((repo_path / "engine" / "strategy_lab").glob("*.py"))
    tos_files = list((repo_path / "engine" / "thinkorswim-scripts").glob("*.pine"))
    doc_files = [p for p in repo_path.glob("JARVIS_TRADER_*.md")]

    file_groups = [
        ("repo_runner", runner_files),
        ("repo_signal", signal_files),
        ("repo_strategy", strategy_files),
        ("repo_strategy", lab_files),
        ("tos_script", tos_files),
        ("analysis_doc", doc_files),
    ]

    for source_type, files in file_groups:
        for fpath in files:
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.warning(f"Could not read {fpath}: {e}")
                continue

            # Skip clearly non-strategy files
            if source_type == "repo_strategy" and len(content) < 200:
                continue

            # Heuristic pre-filter: must mention at least one trading concept
            if not _has_trading_signal(content):
                continue

            atom = _extract_atom_from_file(fpath, content, source_type, llm_extract_fn)
            if atom:
                atoms.append(atom)

    logger.info(f"Extracted {len(atoms)} repo atoms")
    return atoms


def _has_trading_signal(content: str) -> bool:
    """Quick pre-filter — does this file mention any trading concept?"""
    lc = content.lower()
    triggers = [
        "entry", "exit", "long", "short", "signal", "backtest",
        "sharpe", "drawdown", "stop", "target", "indicator", "strategy",
    ]
    return any(t in lc for t in triggers)


def _extract_atom_from_file(fpath: Path, content: str, source_type: str, llm_extract_fn) -> Optional[HypothesisAtom]:
    """Use LLM + heuristics to extract a hypothesis atom from one file."""

    # Heuristic extraction (free, deterministic)
    category, cat_ambiguous, cat_runners = _detect_category(content)
    instrument_class, raw_instruments = _detect_instruments(content, fpath.name)
    timeframe_class, raw_timeframes = _detect_timeframes(content)
    entry_kw = _extract_keywords(content, ["entry", "long when", "short when", "buy when", "sell when"])
    exit_kw = _extract_keywords(content, ["exit", "stop", "target", "close when"])
    param_names, param_defaults = _extract_parameters(content)

    # LLM extraction (for economic_rationale_draft and rationale_strength)
    rationale, strength = llm_extract_fn(fpath, content, source_type) if llm_extract_fn else ("", "MISSING")

    if not category and not instrument_class and source_type == "repo_strategy":
        # Not actually a strategy file
        return None

    # Patch 3: IS_LIBRARY detection
    is_library = _is_library_file(fpath, content, instrument_class, source_type)

    return HypothesisAtom(
        source_type=source_type,
        source_path=str(fpath),
        source_metadata={"file_size": len(content), "last_modified": datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc).isoformat()},
        category=category,
        subcategory=None,
        instrument_class=instrument_class,
        raw_instruments=raw_instruments,
        timeframe_class=timeframe_class,
        raw_timeframes=raw_timeframes,
        entry_keywords=entry_kw,
        exit_keywords=exit_kw,
        parameter_names=param_names,
        parameter_defaults=param_defaults,
        claimed_metrics={},
        economic_rationale_draft=rationale,
        rationale_strength=strength,
        raw_text_sample=content[:500],
        is_library=is_library,
        category_ambiguous=cat_ambiguous,
        category_runners_up=cat_runners,
    )


def _is_library_file(fpath: Path, content: str, instrument_class: Optional[str], source_type: str) -> bool:
    """True if this file is an instrument-agnostic helper, not a runnable strategy."""
    if source_type == "repo_runner":
        return False
    name = fpath.name.lower()
    library_suffixes = ("_signals.py", "_utils.py", "_helpers.py", "_primitives.py", "_base.py")
    has_lib_suffix = any(name.endswith(s) for s in library_suffixes)
    has_main = "if __name__" in content
    return has_lib_suffix and not has_main and not instrument_class


def _detect_category(content: str) -> tuple[Optional[str], bool, list[str]]:
    """Returns (best_category, is_ambiguous, runners_up).

    Patch 5: discount keywords inside filter expressions (e.g. 'vix' in
    'if vix > 20: continue' is a regime filter, not a volatility strategy).
    Ambiguous = top-2 within 30% of each other.
    """
    lc = content.lower()
    scores = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in kws:
            count = lc.count(kw)
            filter_pattern = rf"if[^\n]{{0,80}}\b{re.escape(kw)}\b"
            filter_count = len(re.findall(filter_pattern, lc))
            adjusted = max(0, count - filter_count // 2)
            score += adjusted
        scores[cat] = score

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    best_cat, best_score = ranked[0]
    if best_score == 0:
        return None, False, []
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    ambiguous = second_score > 0 and (best_score - second_score) / max(1, best_score) < 0.30
    runners_up = [c for c, s in ranked[1:4] if s > 0]
    return best_cat, ambiguous, runners_up


def _detect_instruments(content: str, filename: str) -> tuple[Optional[str], list[str]]:
    """Detect primary instrument class and all raw instrument symbols mentioned.

    Patch 1: filename mentions weighted 3x vs body mentions. Runners are named
    after their primary instrument; body mentions are often filters or
    cross-instrument comparisons.
    """
    body_lc = content.lower()
    fname_lc = filename.lower()

    symbol_scores: dict[str, int] = {}
    raw: set[str] = set()

    for cls, symbols in INSTRUMENT_CLASSES.items():
        for sym in symbols:
            pattern = rf"\b{re.escape(sym)}\b"
            body_count = len(re.findall(pattern, body_lc))
            fname_count = len(re.findall(pattern, fname_lc))
            total = body_count + fname_count * 3
            if total > 0:
                raw.add(sym.upper())
                symbol_scores[sym.upper()] = symbol_scores.get(sym.upper(), 0) + total

    if not raw:
        return None, []

    top_sym = max(symbol_scores.items(), key=lambda x: x[1])[0]
    primary_class = _INSTRUMENT_TO_CLASS.get(top_sym)
    return primary_class, sorted(raw)


def _detect_timeframes(content: str) -> tuple[Optional[str], list[str]]:
    lc = content.lower()
    raw = []
    for tf in ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]:
        if re.search(rf"\b{tf}\b|'{tf}'|\"{tf}\"", content):
            raw.append(tf)
    if not raw:
        return None, []
    # Map to class
    for cls, tfs in TF_CLASSES.items():
        if any(tf in tfs for tf in raw):
            return cls, raw
    return None, raw


def _extract_keywords(content: str, anchors: list[str]) -> list[str]:
    """Extract words near anchor phrases."""
    keywords = set()
    lc = content.lower()
    for anchor in anchors:
        for m in re.finditer(re.escape(anchor), lc):
            start = max(0, m.start() - 100)
            end = min(len(content), m.end() + 150)
            snippet = content[start:end]
            # Pull out indicator/concept words
            for word in re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]{2,}\b", snippet):
                wl = word.lower()
                if wl in {"the", "and", "for", "with", "when", "this", "that", "from", "into", "than", "then"}:
                    continue
                keywords.add(wl)
    return sorted(keywords)[:10]


def _extract_parameters(content: str) -> tuple[list[str], dict]:
    """Pull out parameter-looking variables from the file."""
    params = {}
    # Look for UPPERCASE_CONST = number patterns
    for m in re.finditer(r"\b([A-Z][A-Z0-9_]{2,})\s*=\s*([0-9.]+)\b", content):
        name, val = m.group(1), m.group(2)
        if name in {"TRUE", "FALSE", "NONE"}:
            continue
        try:
            params[name.lower()] = float(val) if "." in val else int(val)
        except ValueError:
            pass
    # Look for snake_case params in function signatures
    for m in re.finditer(r"def\s+\w+\s*\(([^)]+)\)", content):
        sig = m.group(1)
        for param_match in re.finditer(r"(\w+)\s*[:=]\s*([0-9.]+)", sig):
            pname, pval = param_match.group(1), param_match.group(2)
            try:
                params[pname] = float(pval) if "." in pval else int(pval)
            except ValueError:
                pass
    return sorted(params.keys()), params


# ── Atom Extraction: Bookmarks ───────────────────────────────────────────────


def extract_bookmark_atoms(bookmarks_path: Path, llm_extract_fn) -> list[HypothesisAtom]:
    """Parse the OneDrive bookmarks export and extract one atom per bookmark."""
    atoms: list[HypothesisAtom] = []

    if not bookmarks_path.exists():
        logger.warning(f"Bookmarks file not found: {bookmarks_path} — skipping bookmark extraction")
        return atoms

    if bookmarks_path.suffix.lower() == ".json":
        bookmarks = _parse_bookmarks_json(bookmarks_path)
    elif bookmarks_path.suffix.lower() in {".html", ".htm"}:
        bookmarks = _parse_bookmarks_html(bookmarks_path)
    else:
        logger.error(f"Unsupported bookmarks format: {bookmarks_path.suffix}")
        return atoms

    for bm in bookmarks:
        atom = _extract_atom_from_bookmark(bm, llm_extract_fn)
        if atom:
            atoms.append(atom)

    logger.info(f"Extracted {len(atoms)} bookmark atoms from {len(bookmarks)} bookmarks")
    return atoms


def _parse_bookmarks_json(path: Path) -> list[dict]:
    """Expect a JSON array of objects: [{url, text, author, saved_at, ...}, ...]"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "bookmarks" in data:
        return data["bookmarks"]
    return data


def _parse_bookmarks_html(path: Path) -> list[dict]:
    """Parse an HTML export — typical browser bookmark dump or X bookmark export tool output."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("beautifulsoup4 is required for HTML bookmark parsing. pip install beautifulsoup4")
        return []

    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    bookmarks = []
    # Generic strategy: find all <a> tags pointing to x.com / twitter.com
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "x.com" in href or "twitter.com" in href:
            # Try to get nearby text (the tweet content if it was captured)
            parent_text = a.parent.get_text(" ", strip=True) if a.parent else a.get_text(strip=True)
            bookmarks.append({
                "url": href,
                "text": parent_text[:2000],
                "author": _extract_handle_from_url(href),
                "saved_at": None,
            })
    return bookmarks


def _extract_handle_from_url(url: str) -> str:
    m = re.search(r"(?:x|twitter)\.com/([^/]+)/", url)
    return f"@{m.group(1)}" if m else ""


def _extract_atom_from_bookmark(bm: dict, llm_extract_fn) -> Optional[HypothesisAtom]:
    text = bm.get("text", "") or ""
    if len(text) < 30:
        return None

    # Filter: must look like trading content
    lc = text.lower()
    trading_signals = ["es", "spx", "spy", "nq", "vix", "future", "option", "stock", "trade", "long", "short", "buy", "sell", "strategy", "setup", "edge", "sharpe", "win rate", "r:r"]
    if not any(t in lc for t in trading_signals):
        return None

    category, _cat_ambiguous, _cat_runners = _detect_category(text)
    instrument_class, raw_instruments = _detect_instruments(text, "")
    timeframe_class, raw_timeframes = _detect_timeframes(text)
    entry_kw = _extract_keywords(text, ["entry", "enter when", "long when", "short when", "buy when", "sell when"])
    exit_kw = _extract_keywords(text, ["exit", "stop", "target", "tp", "sl"])
    claimed_metrics = _extract_claimed_metrics(text)

    rationale, strength = llm_extract_fn(bm.get("url", ""), text, "bookmark") if llm_extract_fn else ("", "MISSING")

    return HypothesisAtom(
        source_type="bookmark",
        source_path=bm.get("url", ""),
        source_metadata={"author_handle": bm.get("author", ""), "saved_at": bm.get("saved_at", "")},
        category=category,
        subcategory=None,
        instrument_class=instrument_class,
        raw_instruments=raw_instruments,
        timeframe_class=timeframe_class,
        raw_timeframes=raw_timeframes,
        entry_keywords=entry_kw,
        exit_keywords=exit_kw,
        parameter_names=[],
        parameter_defaults={},
        claimed_metrics=claimed_metrics,
        economic_rationale_draft=rationale,
        rationale_strength=strength,
        raw_text_sample=text[:500],
    )


def _extract_claimed_metrics(text: str) -> dict:
    metrics = {}
    # Sharpe
    m = re.search(r"sharpe[:\s]+(\d+\.?\d*)", text, re.IGNORECASE)
    if m:
        metrics["sharpe"] = float(m.group(1))
    # Win rate
    m = re.search(r"(\d+)%?\s*win\s*rate", text, re.IGNORECASE)
    if m:
        metrics["win_rate"] = int(m.group(1)) / 100.0 if int(m.group(1)) > 1 else float(m.group(1))
    # R-multiple
    m = re.search(r"(\d+\.?\d*)R\s*target", text, re.IGNORECASE)
    if m:
        metrics["target_r"] = float(m.group(1))
    return metrics


# ── Merge Logic ──────────────────────────────────────────────────────────────


def compute_similarity(a: HypothesisAtom, b: HypothesisAtom) -> float:
    """Cross-source similarity per references/bookmark_to_code_mapping.md."""
    cat_match = 1.0 if a.category == b.category else (0.5 if _adjacent_category(a.category, b.category) else 0.0)
    inst_match = _instrument_match(a.instrument_class, b.instrument_class)
    tf_match = _timeframe_match(a.timeframe_class, b.timeframe_class)
    kw_overlap = _jaccard(set(a.entry_keywords + a.exit_keywords), set(b.entry_keywords + b.exit_keywords))
    param_overlap = _jaccard(set(a.parameter_names), set(b.parameter_names)) if a.parameter_names and b.parameter_names else 0.0

    return 0.30 * cat_match + 0.20 * inst_match + 0.20 * tf_match + 0.20 * kw_overlap + 0.10 * param_overlap


def _adjacent_category(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    adjacencies = {
        ("breakout", "momentum"), ("momentum", "trend_following"),
        ("mean_reversion", "volatility"), ("seasonality", "event_driven"),
    }
    return (a, b) in adjacencies or (b, a) in adjacencies


def _instrument_match(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Index futures are loosely related
    index_classes = {"es", "nq", "rty"}
    if a in index_classes and b in index_classes:
        return 0.7
    return 0.0


def _timeframe_match(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    adjacencies = {("intraday", "swing"), ("overnight", "multiday"), ("swing", "multiday")}
    if (a, b) in adjacencies or (b, a) in adjacencies:
        return 0.5
    return 0.0


def _jaccard(s1: set, s2: set) -> float:
    if not s1 and not s2:
        return 0.0
    return len(s1 & s2) / max(1, len(s1 | s2))


def merge_atoms(repo_atoms: list[HypothesisAtom], bookmark_atoms: list[HypothesisAtom]) -> tuple[list[StrategyCard], list[dict], list[HypothesisAtom]]:
    """Returns (final_cards, candidate_merges_for_review, library_atoms).

    Patch 2 + 3: separate analysis_doc atoms and library atoms from
    card-eligible atoms. Doc atoms cannot create standalone cards — they only
    enrich existing cards via _attach_doc_atoms_to_cards. Library atoms are
    excluded from card creation entirely (returned to caller for separate logging).
    """

    # Separate special-purpose atoms
    doc_atoms = [a for a in repo_atoms if a.source_type == "analysis_doc"]
    library_atoms = [a for a in repo_atoms if a.is_library]
    eligible_repo_atoms = [a for a in repo_atoms
                           if a.source_type != "analysis_doc" and not a.is_library]

    # Step 1: dedup within repo
    repo_groups = _group_repo_atoms(eligible_repo_atoms)

    # Step 2: dedup within bookmarks
    bookmark_groups = _group_bookmark_atoms(bookmark_atoms)

    # Step 3: cross-source merging
    cards: list[StrategyCard] = []
    candidate_merges: list[dict] = []
    used_bookmark_groups: set[int] = set()

    for rgroup in repo_groups:
        best_bgroup_idx = None
        best_score = 0.0
        for i, bgroup in enumerate(bookmark_groups):
            if i in used_bookmark_groups:
                continue
            # Use the representative atom of each group for similarity
            score = compute_similarity(rgroup[0], bgroup[0])
            if score > best_score:
                best_score = score
                best_bgroup_idx = i

        if best_score >= 0.80 and best_bgroup_idx is not None:
            # Auto-merge
            card = _build_card_from_groups(rgroup, bookmark_groups[best_bgroup_idx])
            cards.append(card)
            used_bookmark_groups.add(best_bgroup_idx)
        elif best_score >= 0.50 and best_bgroup_idx is not None:
            # Candidate merge — flag for review
            card = _build_card_from_groups(rgroup, [])
            cards.append(card)
            candidate_merges.append({
                "card_hypothesis_id": card.hypothesis_id,
                "candidate_bookmark_urls": [a.source_path for a in bookmark_groups[best_bgroup_idx]],
                "similarity_score": round(best_score, 3),
                "reason": "Medium-confidence cross-source match — review and merge or reject",
            })
        else:
            card = _build_card_from_groups(rgroup, [])
            cards.append(card)

    # Step 4: bookmark groups with no repo match → standalone cards
    for i, bgroup in enumerate(bookmark_groups):
        if i in used_bookmark_groups:
            continue
        card = _build_card_from_groups([], bgroup)
        cards.append(card)

    # Step 5 (Patch 2): attach analysis_doc atoms to existing cards by similarity
    _attach_doc_atoms_to_cards(cards, doc_atoms)

    # Step 6 (Patch 4): disambiguate hypothesis_id collisions
    _disambiguate_ids(cards)

    return cards, candidate_merges, library_atoms


def _attach_doc_atoms_to_cards(cards: list[StrategyCard], doc_atoms: list[HypothesisAtom]) -> None:
    """Patch 2: analysis docs enrich existing cards — never create new ones.

    For each doc atom, attach to any card with similarity ≥ 0.40 by
    (category, instrument_class, timeframe_class). Match score is logged.
    """
    if not doc_atoms or not cards:
        return
    now = datetime.now(timezone.utc).isoformat()

    profiles = []
    for card in cards:
        profiles.append({
            "card": card,
            "category": card.category,
            "instrument_class": _INSTRUMENT_TO_CLASS.get(card.instruments.get("primary", "")),
            "timeframe_class": _tf_to_class(card.timeframes.get("primary", "")),
        })

    for atom in doc_atoms:
        for prof in profiles:
            cat_match = 1.0 if atom.category == prof["category"] else 0.0
            inst_match = _instrument_match(atom.instrument_class, prof["instrument_class"])
            tf_match = _timeframe_match(atom.timeframe_class, prof["timeframe_class"])
            score = 0.40 * cat_match + 0.30 * inst_match + 0.30 * tf_match
            if score >= 0.40:
                prof["card"].provenance["external_doc_sources"].append({
                    "path": atom.source_path,
                    "section": "",
                    "last_seen": now,
                    "match_score": round(score, 3),
                })


def _tf_to_class(tf: str) -> Optional[str]:
    for cls, tfs in TF_CLASSES.items():
        if tf in tfs:
            return cls
    return None


def _disambiguate_ids(cards: list[StrategyCard]) -> None:
    """Patch 4: append 6-char content hash to colliding hypothesis_ids."""
    seen = Counter(c.hypothesis_id for c in cards)
    for card in cards:
        if seen[card.hypothesis_id] > 1:
            sources = card.provenance.get("repo_sources", []) or card.provenance.get("bookmark_sources", [])
            if sources:
                seed = sources[0].get("path") or sources[0].get("url") or card.name
            else:
                seed = card.name
            h = hashlib.md5(str(seed).encode()).hexdigest()[:6]
            card.hypothesis_id = f"{card.hypothesis_id}_{h}"


def _group_repo_atoms(atoms: list[HypothesisAtom]) -> list[list[HypothesisAtom]]:
    """Group repo atoms that obviously implement the same strategy."""
    groups: dict[str, list[HypothesisAtom]] = {}
    for atom in atoms:
        key = _repo_group_key(atom)
        groups.setdefault(key, []).append(atom)
    return list(groups.values())


def _repo_group_key(atom: HypothesisAtom) -> str:
    """Group by (category, instrument_class, timeframe_class, normalized stem).

    Patch 6: strip noise tokens from the stem before grouping so that
    e.g. run_mes_trend_rank1, run_mes_trend_rank2, run_mgc_trend_rank3
    all group together as 'trend' — BUT only when their (category,
    instrument_class) keys agree. Different instruments produce different
    groups by design, so cross-instrument merging happens via card-level
    instrument modal logic, not at the group level.
    """
    stem = Path(atom.source_path).stem
    base = re.sub(r"^(run_)?(mes|mnq|mgc|mcl|m2k|es|nq|gc|cl|rty)_", "", stem, flags=re.IGNORECASE)
    base = re.sub(r"_rank\d+.*$", "", base)
    base = re.sub(r"_(signals|backtester|wfo|runner|walk_forward|backtest)$", "", base)
    tokens = [t for t in base.split("_") if t and t.lower() not in _DESCRIPTOR_NOISE]
    base = "_".join(tokens) if tokens else "generic"
    return f"{atom.category or 'unk'}|{atom.instrument_class or 'unk'}|{atom.timeframe_class or 'unk'}|{base}"


def _group_bookmark_atoms(atoms: list[HypothesisAtom]) -> list[list[HypothesisAtom]]:
    """Group bookmarks from the same author within 7 days describing the same cat+inst."""
    groups: dict[str, list[HypothesisAtom]] = {}
    for atom in atoms:
        key = f"{atom.source_metadata.get('author_handle', '')}|{atom.category}|{atom.instrument_class}"
        groups.setdefault(key, []).append(atom)
    return list(groups.values())


def _build_card_from_groups(repo_group: list[HypothesisAtom], bookmark_group: list[HypothesisAtom]) -> StrategyCard:
    """Build a final StrategyCard from a merged group of atoms."""
    all_atoms = repo_group + bookmark_group
    primary = repo_group[0] if repo_group else bookmark_group[0]

    hypothesis_id = _make_hypothesis_id(primary)
    now = datetime.now(timezone.utc).isoformat()

    card = StrategyCard(
        hypothesis_id=hypothesis_id,
        created_at=now,
        updated_at=now,
        name=_make_name(primary),
        category=primary.category or "uncategorized",
        subcategory=primary.subcategory or "",
        economic_rationale=primary.economic_rationale_draft or "",
        rationale_strength=primary.rationale_strength or "MISSING",
    )

    # Instruments (Patch 1): primary = modal weighted across all atoms
    all_instruments = set()
    for a in all_atoms:
        all_instruments.update(a.raw_instruments)

    instrument_votes: Counter = Counter()
    for a in all_atoms:
        for sym in a.raw_instruments:
            weight = 3 if a.source_type == "repo_runner" else 1
            if a.source_type.startswith("repo") and sym.lower() in Path(a.source_path).name.lower():
                weight *= 2
            instrument_votes[sym] += weight

    modal_instrument = instrument_votes.most_common(1)[0][0] if instrument_votes else ""
    card.instruments = {
        "primary": modal_instrument,
        "tested_on": sorted(all_instruments) if repo_group else [],
        "applicable_to": sorted(all_instruments),
        "do_not_use_on": [],
    }

    # Timeframes
    all_tfs = set()
    for a in all_atoms:
        all_tfs.update(a.raw_timeframes)
    card.timeframes = {
        "primary": primary.raw_timeframes[0] if primary.raw_timeframes else "",
        "applicable": sorted(all_tfs),
        "rationale_for_tf": "",
    }

    # Parameters (from repo)
    if repo_group:
        card.parameters = repo_group[0].parameter_defaults

    # Provenance
    for atom in repo_group:
        if atom.source_type == "analysis_doc":
            card.provenance["external_doc_sources"].append({
                "path": atom.source_path,
                "section": "",
                "last_seen": now,
            })
        else:
            card.provenance["repo_sources"].append({
                "path": atom.source_path,
                "git_sha": "",  # filled in by run_phase.py with current HEAD
                "role": atom.source_type,
                "last_seen": now,
            })

    for atom in bookmark_group:
        card.provenance["bookmark_sources"].append({
            "url": atom.source_path,
            "author_handle": atom.source_metadata.get("author_handle", ""),
            "saved_at": atom.source_metadata.get("saved_at", ""),
            "claim_summary": atom.raw_text_sample[:300],
            "claim_verified_in_repo": bool(repo_group),
        })

    # Untested variants from bookmarks
    for atom in bookmark_group:
        for variant_keyword in atom.entry_keywords + atom.exit_keywords:
            if repo_group and variant_keyword not in (repo_group[0].entry_keywords + repo_group[0].exit_keywords):
                card.untested_variants_from_bookmarks.append(f"Bookmark mentions: {variant_keyword}")

    # Implementation status
    card.implementation_status["exists_in_repo"] = bool(repo_group)
    card.implementation_status["has_backtest"] = any("backtest" in str(a.source_path).lower() for a in repo_group)
    card.implementation_status["has_walk_forward"] = any("wfo" in str(a.source_path).lower() or "walk_forward" in str(a.source_path).lower() for a in repo_group)

    # Phase 1 status
    if card.rationale_strength == "MISSING" or len(card.economic_rationale) < 50:
        card.phase_1_status = "NEEDS_RATIONALE"
        card.next_action = "Write economic_rationale (≥50 chars) before Phase 2"
    elif not repo_group:
        card.phase_1_status = "NEEDS_IMPLEMENTATION"
        card.next_action = "Implement in engine/strategies/ before Phase 2"
    else:
        card.phase_1_status = "PASSED"
        card.next_action = f"Phase 2 smoke test on {card.instruments['primary'] or 'ES'} {card.timeframes['primary'] or '5m'}, 24mo, author defaults"

    return card


def _make_hypothesis_id(atom: HypothesisAtom) -> str:
    """Generate canonical hypothesis_id following the schema."""
    cat = atom.category or "uncat"
    desc = _make_descriptor(atom)
    inst = atom.instrument_class or "multi"
    tf = atom.timeframe_class or "unknown"
    return f"{cat}_{desc}_{inst}_{tf}"


def _make_descriptor(atom: HypothesisAtom) -> str:
    """Patch 6: short descriptor for hypothesis_id with noise tokens stripped."""
    if atom.source_type.startswith("repo"):
        stem = Path(atom.source_path).stem
        base = re.sub(r"^(run_)?(mes|mnq|mgc|mcl|m2k|es|nq|gc|cl|rty)_", "", stem, flags=re.IGNORECASE)
        base = re.sub(r"_rank\d+.*$", "", base)
        base = re.sub(r"_(signals|backtester|wfo|runner|walk_forward|backtest)$", "", base)
        tokens = [t for t in base.split("_") if t and t.lower() not in _DESCRIPTOR_NOISE]
        cleaned = "_".join(tokens)
        if cleaned and cleaned != stem:
            return cleaned[:30]
    kws = [k for k in (atom.entry_keywords + atom.exit_keywords) if k.lower() not in _DESCRIPTOR_NOISE]
    if kws:
        return "_".join(kws[:2])[:30]
    return "generic"


def _make_name(atom: HypothesisAtom) -> str:
    parts = [atom.category, atom.subcategory, atom.instrument_class, atom.timeframe_class]
    return " — ".join(p.replace("_", " ").title() for p in parts if p)


# ── LLM Extraction (pluggable) ───────────────────────────────────────────────


def get_llm_extract_fn():
    """Returns a function (source_id, content, source_type) -> (rationale_str, strength_str)."""
    provider = os.environ.get("JARVIS_FUNNEL_LLM_PROVIDER", "").lower()

    if provider == "anthropic":
        return _anthropic_extract_fn()
    elif provider == "openai":
        return _openai_extract_fn()
    else:
        logger.warning("No JARVIS_FUNNEL_LLM_PROVIDER set — using heuristic-only extraction. Rationale quality will be poor.")
        return _heuristic_extract_fn


def _heuristic_extract_fn(source_id, content, source_type) -> tuple[str, str]:
    """Free fallback — extract docstrings or first comment block as 'rationale'."""
    if isinstance(content, str):
        # Look for module docstring
        m = re.search(r'"""(.*?)"""', content, re.DOTALL)
        if m:
            text = m.group(1).strip()[:800]
            return text, "MODERATE" if len(text) >= 100 else "WEAK"
        # Look for top-of-file comments
        comments = "\n".join(line.lstrip("# ").strip() for line in content.split("\n")[:30] if line.strip().startswith("#"))
        if len(comments) >= 50:
            return comments[:800], "WEAK"
    return "", "MISSING"


def _anthropic_extract_fn():
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed. pip install anthropic")
        return _heuristic_extract_fn

    client = anthropic.Anthropic()
    model = os.environ.get("JARVIS_FUNNEL_LLM_MODEL", "claude-sonnet-4-20250514")

    def extract(source_id, content, source_type) -> tuple[str, str]:
        prompt = f"""You are analyzing a trading strategy source ({source_type}: {source_id}).

Extract the ECONOMIC RATIONALE for why this strategy might have edge. Focus on:
- What market behavior or inefficiency does it exploit?
- Who is on the other side of these trades and why?
- When/why might the edge persist or decay?

Then rate the rationale strength: STRONG (clear, well-articulated, falsifiable), MODERATE (plausible, some hand-waving), WEAK (vague or just "indicator says X"), MISSING (no rationale provided).

Content (truncated):
{content[:4000]}

Respond in JSON format ONLY:
{{"rationale": "...", "strength": "STRONG|MODERATE|WEAK|MISSING"}}"""

        try:
            resp = client.messages.create(
                model=model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                return data.get("rationale", "")[:1500], data.get("strength", "MISSING")
        except Exception as e:
            logger.warning(f"LLM extraction failed for {source_id}: {e}")
        return "", "MISSING"

    return extract


def _openai_extract_fn():
    try:
        import openai
    except ImportError:
        logger.error("openai package not installed. pip install openai")
        return _heuristic_extract_fn

    client = openai.OpenAI()
    model = os.environ.get("JARVIS_FUNNEL_LLM_MODEL", "gpt-4o")

    def extract(source_id, content, source_type) -> tuple[str, str]:
        prompt = f"""You are analyzing a trading strategy source ({source_type}: {source_id}).

Extract the ECONOMIC RATIONALE for why this strategy might have edge. Focus on:
- What market behavior or inefficiency does it exploit?
- Who is on the other side of these trades and why?
- When/why might the edge persist or decay?

Then rate the rationale strength: STRONG / MODERATE / WEAK / MISSING.

Content (truncated):
{content[:4000]}

Respond in JSON format ONLY: {{"rationale": "...", "strength": "..."}}"""
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=600,
            )
            data = json.loads(resp.choices[0].message.content)
            return data.get("rationale", "")[:1500], data.get("strength", "MISSING")
        except Exception as e:
            logger.warning(f"LLM extraction failed for {source_id}: {e}")
        return "", "MISSING"

    return extract


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Phase 1 inventory pipeline for the Jarvis Robust Strategy Funnel")
    parser.add_argument("--repo", type=Path, required=True, help="Path to local jarvis-trader repo")
    parser.add_argument("--bookmarks", type=Path, default=None, help="Path to bookmarks export (.json or .html)")
    parser.add_argument("--out", type=Path, required=True, help="Output path for strategies_v1.jsonl")
    parser.add_argument("--side-artifacts-dir", type=Path, default=None, help="Where to write atoms_*.jsonl, merge_review.jsonl")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    llm_fn = get_llm_extract_fn()

    logger.info("=== Phase 1: extracting repo atoms ===")
    repo_atoms = extract_repo_atoms(args.repo, llm_fn)

    logger.info("=== Phase 1: extracting bookmark atoms ===")
    bookmark_atoms = extract_bookmark_atoms(args.bookmarks, llm_fn) if args.bookmarks else []

    logger.info("=== Phase 1: merging atoms into strategy cards ===")
    cards, candidate_merges, library_atoms = merge_atoms(repo_atoms, bookmark_atoms)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for card in cards:
            f.write(json.dumps(card.to_dict()) + "\n")
    logger.info(f"Wrote {len(cards)} strategy cards to {args.out}")

    # Side artifacts
    side_dir = args.side_artifacts_dir or args.out.parent
    side_dir.mkdir(parents=True, exist_ok=True)
    with (side_dir / "atoms_repo.jsonl").open("w", encoding="utf-8") as f:
        for a in repo_atoms:
            f.write(json.dumps(a.to_dict()) + "\n")
    with (side_dir / "library_atoms.jsonl").open("w", encoding="utf-8") as f:
        for a in library_atoms:
            f.write(json.dumps(a.to_dict()) + "\n")
    with (side_dir / "atoms_bookmarks.jsonl").open("w", encoding="utf-8") as f:
        for a in bookmark_atoms:
            f.write(json.dumps(a.to_dict()) + "\n")
    with (side_dir / "merge_review.jsonl").open("w", encoding="utf-8") as f:
        for m in candidate_merges:
            f.write(json.dumps(m) + "\n")

    # Summary
    by_status = {}
    for card in cards:
        by_status.setdefault(card.phase_1_status or "UNKNOWN", 0)
        by_status[card.phase_1_status or "UNKNOWN"] += 1

    logger.info("=== Phase 1 Summary ===")
    logger.info(f"  Total cards: {len(cards)}")
    for status, count in sorted(by_status.items()):
        logger.info(f"    {status}: {count}")
    logger.info(f"  Candidate merges needing review: {len(candidate_merges)}")
    logger.info(f"  Atoms — repo: {len(repo_atoms)}, bookmarks: {len(bookmark_atoms)}, libraries: {len(library_atoms)}")
    logger.info(f"  Inventory version: {INVENTORY_VERSION}")


if __name__ == "__main__":
    main()
