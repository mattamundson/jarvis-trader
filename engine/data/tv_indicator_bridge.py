"""
TVIndicatorBridge — reads all JARVIS Pine Script indicator values from
TradingView Desktop via the TradingView MCP CLI (`tv` command).

Primary entry point: get_snapshot(symbol) -> TVIndicatorSnapshot

Reading strategy:
  1. First try JARVIS_MCP_Manifest (single call, all data)
  2. If manifest unavailable, fall back to reading individual indicators
  3. If TradingView is offline, return snapshot with data_quality="unavailable"

Cache: 60-second TTL per symbol — TradingView data does not need real-time polling
"""

import json
import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TV_CLI = "tv"
_CACHE_TTL_SECONDS = 60


@dataclass
class TVIndicatorSnapshot:
    # STC
    stc_value: Optional[float] = None       # 0-100
    stc_state: Optional[str] = None         # OVERSOLD/OVERBOUGHT/BULLISH/BEARISH
    stc_ob: float = 83.0
    stc_os: float = 15.0

    # Composite Score
    composite_score: Optional[float] = None  # -1.0 to +1.0
    regime: Optional[str] = None             # TRENDING_BULL/BEAR/RANGING/COMPRESSION/VOLATILE
    orb_high: Optional[float] = None
    orb_low: Optional[float] = None
    vwap: Optional[float] = None
    vwap_upper: Optional[float] = None
    vwap_lower: Optional[float] = None

    # ATR
    atr_value: Optional[float] = None
    tr_pct: Optional[float] = None
    atr_neg1: Optional[float] = None
    atr_pos1: Optional[float] = None
    atr_neg2: Optional[float] = None
    atr_pos2: Optional[float] = None
    atr_neg3: Optional[float] = None
    atr_pos3: Optional[float] = None
    lower_trig: Optional[float] = None
    upper_trig: Optional[float] = None

    # IB Levels
    ib_high: Optional[float] = None
    ib_low: Optional[float] = None
    ib_range: Optional[float] = None
    ib_mid: Optional[float] = None
    ibu50: Optional[float] = None
    ibu100: Optional[float] = None
    ibd50: Optional[float] = None
    ibd100: Optional[float] = None
    ib_complete: bool = False

    # Phase Oscillator
    phase_oscillator: Optional[float] = None  # +-100
    is_compressed: bool = False
    phase_state: Optional[str] = None

    # Corey Score
    corey_score: Optional[float] = None      # -1.0 to +1.0
    corey_bias: Optional[str] = None

    # Volume
    vol_bull_pct: Optional[float] = None
    vol_bear_pct: Optional[float] = None
    vol_bias: Optional[str] = None

    # Pivot Points
    pivot_pp: Optional[float] = None
    pivot_r1: Optional[float] = None
    pivot_r2: Optional[float] = None
    pivot_r3: Optional[float] = None
    pivot_s1: Optional[float] = None
    pivot_s2: Optional[float] = None
    pivot_s3: Optional[float] = None

    # Keltner
    kc_upper: Optional[float] = None
    kc_mid: Optional[float] = None
    kc_lower: Optional[float] = None

    # Volume Profile
    vp_poc: Optional[float] = None
    vp_vah: Optional[float] = None
    vp_val: Optional[float] = None
    vp_bias: Optional[str] = None

    # Gap
    gap_exists: bool = False
    gap_direction: Optional[str] = None
    gap_high: Optional[float] = None
    gap_low: Optional[float] = None
    gap_filled: bool = False

    # Market Cycle
    cycle_phase: Optional[str] = None
    cycle_score: Optional[float] = None

    # OTE
    ote_bull_high: Optional[float] = None
    ote_bull_low: Optional[float] = None
    ote_bear_high: Optional[float] = None
    ote_bear_low: Optional[float] = None
    in_bull_ote: bool = False
    in_bear_ote: bool = False
    mid_cloud: Optional[float] = None

    # VPOC
    vpoc_today: Optional[float] = None
    vpoc_yesterday: Optional[float] = None
    vpoc_delta: Optional[float] = None

    # Keltner bias
    kc_alignment: Optional[str] = None

    # Gamma Levels — read from "MY FREE GAMMA LEVELS" overlay (TheRealDrip2Rip)
    # via MCP label passthrough; source script is closed, so we never compute
    # these ourselves. Missing indicator → all fields remain None.
    gex_flip: Optional[float] = None          # zero-gamma boundary
    call_wall: Optional[float] = None         # largest call OI strike
    put_wall: Optional[float] = None          # largest put OI strike
    hvl: Optional[float] = None               # high volatility level
    vol_trigger_up: Optional[float] = None    # upside hedge-cascade trigger
    vol_trigger_down: Optional[float] = None  # downside hedge-cascade trigger
    max_pain: Optional[float] = None          # options expiration gravity

    # Quality
    data_quality: str = "unavailable"  # "live" | "stale" | "unavailable"
    source: str = "tradingview"
    timestamp: Optional[datetime] = None
    symbol: Optional[str] = None


# Gamma-level alias table. Vendor script is closed-source, so we match on
# several plausible text substrings per level. Order within each list matters
# only for readability — each label can populate at most one key (first hit).
_GAMMA_ALIASES: Dict[str, tuple] = {
    "gex_flip": ("gex flip", "zero gamma", "flip"),
    "call_wall": ("call wall",),
    "put_wall": ("put wall",),
    "hvl": ("hvl", "high volatility"),
    "vol_trigger_up": ("vol trigger up", "upside trigger"),
    "vol_trigger_down": ("vol trigger down", "downside trigger"),
    "max_pain": ("max pain",),
}

# Indicator filter name for the closed-source gamma overlay
_GAMMA_FILTER = "MY FREE GAMMA LEVELS"

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


# Individual indicator filter names used in fallback mode
_INDIVIDUAL_INDICATORS = [
    "JARVIS STC Sub",
    "JARVIS ATR Levels",
    "JARVIS IB Levels",
    "JARVIS Composite Score",
    "JARVIS Phase Oscillator",
    "JARVIS Corey Score",
    "JARVIS Pivot Points",
    "JARVIS Keltner OB Omega",
    "JARVIS Volume Profile",
    "JARVIS Gap Finder",
    "JARVIS Market Cycle",
    "JARVIS OTE Cloud",
    "JARVIS VPOC Tracker",
]


class TVIndicatorBridge:
    """
    Reads all JARVIS Pine Script indicator values from TradingView Desktop
    via the TradingView MCP CLI. Implements 60s TTL cache and graceful
    degradation when TradingView is offline.
    """

    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # symbol -> (snapshot, cache_time)
        self._available: Optional[bool] = None
        self._manifest_available: Optional[bool] = None

    def is_available(self) -> bool:
        """Check if TradingView MCP CLI is reachable."""
        if self._available is not None:
            return self._available

        if not shutil.which(TV_CLI):
            logger.debug("TradingView MCP CLI not found on PATH — bridge unavailable")
            self._available = False
            return False

        try:
            result = subprocess.run(
                [TV_CLI, "health-check"],
                capture_output=True, text=True, timeout=5,
            )
            self._available = result.returncode == 0
            if not self._available:
                logger.debug("TradingView health-check failed: %s", result.stderr.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._available = False

        return self._available

    def get_snapshot(self, symbol: str) -> TVIndicatorSnapshot:
        """
        Main entry point. Returns TVIndicatorSnapshot with all available indicator values.

        Strategy:
          1. Check 60s cache
          2. If TradingView unavailable, return empty snapshot immediately
          3. Try JARVIS_MCP_Manifest first (single CLI call, all data)
          4. Fall back to individual indicator reads
          5. Cache and return result
        """
        # 1. Cache hit
        cached = self._cache.get(symbol)
        if cached is not None:
            snapshot, cache_time = cached
            if time.time() - cache_time < _CACHE_TTL_SECONDS:
                return snapshot

        # 2. Availability guard
        if not self.is_available():
            snap = TVIndicatorSnapshot(symbol=symbol, data_quality="unavailable")
            self._cache[symbol] = (snap, time.time())
            return snap

        # 3. Try manifest
        snapshot: Optional[TVIndicatorSnapshot] = None
        if self._manifest_available is not False:
            labels = self._read_labels("JARVIS MCP Manifest")
            tables = self._read_tables("JARVIS MCP Manifest")
            if labels is not None:
                self._manifest_available = True
                snapshot = self._parse_from_manifest(labels, tables or [])
                snapshot.data_quality = "live"
            else:
                self._manifest_available = False
                logger.debug("JARVIS_MCP_Manifest not available — switching to individual reads")

        # 4. Individual fallback (if manifest absent or empty)
        if snapshot is None:
            indicators_read: Dict[str, Dict[str, Any]] = {}
            for name in _INDIVIDUAL_INDICATORS:
                labels = self._read_labels(name)
                tables = self._read_tables(name)
                if labels is not None or tables is not None:
                    indicators_read[name] = {
                        "labels": labels or [],
                        "tables": tables or [],
                    }
            snapshot = self._parse_from_individual(indicators_read)
            snapshot.data_quality = "live" if indicators_read else "unavailable"

        # 5. Overlay: gamma levels from vendor overlay, if loaded on the chart.
        #    Missing indicator is a no-op — fields stay None.
        self._enrich_with_gamma(snapshot)

        snapshot.symbol = symbol
        snapshot.timestamp = datetime.utcnow()

        # 6. Cache
        self._cache[symbol] = (snapshot, time.time())
        return snapshot

    # ------------------------------------------------------------------
    # CLI helpers
    # ------------------------------------------------------------------

    def _run_tv(self, args: list, timeout: int = 10) -> Optional[str]:
        """Run tv CLI command. Returns stdout on success, None on any failure."""
        try:
            result = subprocess.run(
                [TV_CLI] + args,
                capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
            logger.debug("tv %s failed (rc=%d): %s", " ".join(args), result.returncode, result.stderr.strip())
            return None
        except subprocess.TimeoutExpired:
            logger.debug("tv %s timed out after %ds", " ".join(args), timeout)
            self._available = False
            return None
        except FileNotFoundError:
            self._available = False
            return None
        except Exception as exc:
            logger.debug("tv %s unexpected error: %s", " ".join(args), exc)
            return None

    def _read_labels(self, study_filter: str) -> Optional[list]:
        """Read pine labels from a named indicator. Returns list of dicts or None."""
        raw = self._run_tv(["data", "get-pine-labels", "--filter", study_filter])
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else None
        except json.JSONDecodeError:
            logger.debug("Failed to parse labels JSON for '%s'", study_filter)
            return None

    def _read_tables(self, study_filter: str) -> Optional[list]:
        """Read pine table rows from a named indicator. Returns list of dicts or None."""
        raw = self._run_tv(["data", "get-pine-tables", "--filter", study_filter])
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else None
        except json.JSONDecodeError:
            logger.debug("Failed to parse tables JSON for '%s'", study_filter)
            return None

    # ------------------------------------------------------------------
    # Label parsers
    # ------------------------------------------------------------------

    def _parse_label_float(self, labels: list, key: str) -> Optional[float]:
        """
        Extract float from labels list.
        Labels are {text: "KEY: 1234.56", price: 1234.56} dicts.
        Searches for first label where text starts with 'key: '.
        """
        prefix = key + ": "
        for label in labels:
            text = label.get("text", "") if isinstance(label, dict) else str(label)
            if text.startswith(prefix):
                raw = text[len(prefix):].strip()
                try:
                    return float(raw)
                except ValueError:
                    return None
        return None

    def _parse_label_str(self, labels: list, key: str) -> Optional[str]:
        """Extract string value from label list (the portion after ': ')."""
        prefix = key + ": "
        for label in labels:
            text = label.get("text", "") if isinstance(label, dict) else str(label)
            if text.startswith(prefix):
                return text[len(prefix):].strip() or None
        return None

    def _parse_label_bool(self, labels: list, key: str) -> bool:
        """Parse 'KEY: true' or 'KEY: false' label into bool."""
        val = self._parse_label_str(labels, key)
        if val is None:
            return False
        return val.lower() in ("true", "1", "yes")

    # ------------------------------------------------------------------
    # Manifest parser
    # ------------------------------------------------------------------

    def _parse_from_manifest(self, labels: list, tables: list) -> TVIndicatorSnapshot:
        """
        Parse all values from the JARVIS_MCP_Manifest indicator output.
        The manifest emits all indicator values as labeled annotations.
        """
        pf = self._parse_label_float
        ps = self._parse_label_str
        pb = self._parse_label_bool

        snap = TVIndicatorSnapshot()

        # STC
        snap.stc_value = pf(labels, "STC_VALUE")
        snap.stc_state = ps(labels, "STC_STATE")
        snap.stc_ob = pf(labels, "STC_OB") or 83.0
        snap.stc_os = pf(labels, "STC_OS") or 15.0

        # Composite — JARVIS_MCP_Manifest.pine emits COMP_SCORE/COMP_REGIME
        # (short form). Accept either prefix so older manifests still parse.
        snap.composite_score = pf(labels, "COMP_SCORE")
        if snap.composite_score is None:
            snap.composite_score = pf(labels, "COMPOSITE_SCORE")
        snap.regime = ps(labels, "COMP_REGIME")
        if snap.regime is None:
            snap.regime = ps(labels, "COMPOSITE_REGIME")
        snap.orb_high = pf(labels, "ORB_HIGH")
        snap.orb_low = pf(labels, "ORB_LOW")
        snap.vwap = pf(labels, "VWAP")
        snap.vwap_upper = pf(labels, "VWAP_P1SD")
        snap.vwap_lower = pf(labels, "VWAP_M1SD")

        # ATR — manifest emits ATR_TR_PCT, ATR_LO_TRIG, ATR_HI_TRIG
        snap.atr_value = pf(labels, "ATR_VALUE")
        snap.tr_pct = pf(labels, "ATR_TR_PCT")
        if snap.tr_pct is None:
            snap.tr_pct = pf(labels, "TR_PCT")
        snap.atr_neg1 = pf(labels, "ATR_NEG1")
        snap.atr_pos1 = pf(labels, "ATR_POS1")
        snap.atr_neg2 = pf(labels, "ATR_NEG2")
        snap.atr_pos2 = pf(labels, "ATR_POS2")
        snap.atr_neg3 = pf(labels, "ATR_NEG3")
        snap.atr_pos3 = pf(labels, "ATR_POS3")
        snap.lower_trig = pf(labels, "ATR_LO_TRIG")
        if snap.lower_trig is None:
            snap.lower_trig = pf(labels, "LOWER_TRIG")
        snap.upper_trig = pf(labels, "ATR_HI_TRIG")
        if snap.upper_trig is None:
            snap.upper_trig = pf(labels, "UPPER_TRIG")

        # IB Levels
        snap.ib_high = pf(labels, "IB_HIGH")
        snap.ib_low = pf(labels, "IB_LOW")
        snap.ib_range = pf(labels, "IB_RANGE")
        snap.ib_mid = pf(labels, "IB_MID")
        snap.ibu50 = pf(labels, "IBU50")
        snap.ibu100 = pf(labels, "IBU100")
        snap.ibd50 = pf(labels, "IBD50")
        snap.ibd100 = pf(labels, "IBD100")
        snap.ib_complete = pb(labels, "IB_COMPLETE")

        # Phase Oscillator — manifest emits PHASE_VALUE/PHASE_COMPRESSED
        snap.phase_oscillator = pf(labels, "PHASE_VALUE")
        if snap.phase_oscillator is None:
            snap.phase_oscillator = pf(labels, "PHASE_OSCILLATOR")
        snap.is_compressed = pb(labels, "PHASE_COMPRESSED")
        snap.phase_state = ps(labels, "PHASE_STATE")

        # Corey Score
        snap.corey_score = pf(labels, "COREY_SCORE")
        snap.corey_bias = ps(labels, "COREY_BIAS")

        # Volume
        snap.vol_bull_pct = pf(labels, "VOL_BULL_PCT")
        snap.vol_bear_pct = pf(labels, "VOL_BEAR_PCT")
        snap.vol_bias = ps(labels, "VOL_BIAS")

        # Pivot Points — manifest emits PP, PP_R1..PP_S3
        snap.pivot_pp = pf(labels, "PP")
        snap.pivot_r1 = pf(labels, "PP_R1")
        snap.pivot_r2 = pf(labels, "PP_R2")
        snap.pivot_r3 = pf(labels, "PP_R3")
        snap.pivot_s1 = pf(labels, "PP_S1")
        snap.pivot_s2 = pf(labels, "PP_S2")
        snap.pivot_s3 = pf(labels, "PP_S3")

        # Keltner — manifest emits KC_1H_UPPER/MID/LOWER
        snap.kc_upper = pf(labels, "KC_1H_UPPER")
        if snap.kc_upper is None:
            snap.kc_upper = pf(labels, "KC_UPPER")
        snap.kc_mid = pf(labels, "KC_1H_MID")
        if snap.kc_mid is None:
            snap.kc_mid = pf(labels, "KC_MID")
        snap.kc_lower = pf(labels, "KC_1H_LOWER")
        if snap.kc_lower is None:
            snap.kc_lower = pf(labels, "KC_LOWER")
        snap.kc_alignment = ps(labels, "KC_ALIGNMENT")

        # Volume Profile
        snap.vp_poc = pf(labels, "VP_POC")
        snap.vp_vah = pf(labels, "VP_VAH")
        snap.vp_val = pf(labels, "VP_VAL")
        snap.vp_bias = ps(labels, "VP_BIAS")

        # Gap — manifest emits GAP_DIR (not GAP_DIRECTION)
        snap.gap_exists = pb(labels, "GAP_EXISTS")
        snap.gap_direction = ps(labels, "GAP_DIR")
        if snap.gap_direction is None:
            snap.gap_direction = ps(labels, "GAP_DIRECTION")
        snap.gap_high = pf(labels, "GAP_HIGH")
        snap.gap_low = pf(labels, "GAP_LOW")
        snap.gap_filled = pb(labels, "GAP_FILLED")

        # Market Cycle
        snap.cycle_phase = ps(labels, "CYCLE_PHASE")
        snap.cycle_score = pf(labels, "CYCLE_SCORE")

        # OTE
        snap.ote_bull_high = pf(labels, "OTE_BULL_HIGH")
        snap.ote_bull_low = pf(labels, "OTE_BULL_LOW")
        snap.ote_bear_high = pf(labels, "OTE_BEAR_HIGH")
        snap.ote_bear_low = pf(labels, "OTE_BEAR_LOW")
        snap.in_bull_ote = pb(labels, "IN_BULL_OTE")
        snap.in_bear_ote = pb(labels, "IN_BEAR_OTE")
        snap.mid_cloud = pf(labels, "MID_CLOUD")

        # VPOC
        snap.vpoc_today = pf(labels, "VPOC_TODAY")
        snap.vpoc_yesterday = pf(labels, "VPOC_YESTERDAY")
        snap.vpoc_delta = pf(labels, "VPOC_DELTA")

        return snap

    # ------------------------------------------------------------------
    # Individual indicator fallback parser
    # ------------------------------------------------------------------

    def _parse_from_individual(self, indicators_read: dict) -> TVIndicatorSnapshot:
        """
        Build snapshot from individual indicator reads (manifest fallback).
        indicators_read: {indicator_name: {labels: [...], tables: [...]}}
        """
        snap = TVIndicatorSnapshot()

        def labels_for(name: str) -> list:
            return indicators_read.get(name, {}).get("labels", [])

        pf = self._parse_label_float
        ps = self._parse_label_str
        pb = self._parse_label_bool

        # STC
        stc_labels = labels_for("JARVIS STC Sub")
        snap.stc_value = pf(stc_labels, "STC_VALUE")
        snap.stc_state = ps(stc_labels, "STC_STATE")
        snap.stc_ob = pf(stc_labels, "STC_OB") or 83.0
        snap.stc_os = pf(stc_labels, "STC_OS") or 15.0

        # ATR
        atr_labels = labels_for("JARVIS ATR Levels")
        snap.atr_value = pf(atr_labels, "ATR_VALUE")
        snap.tr_pct = pf(atr_labels, "TR_PCT")
        snap.atr_neg1 = pf(atr_labels, "ATR_NEG1")
        snap.atr_pos1 = pf(atr_labels, "ATR_POS1")
        snap.atr_neg2 = pf(atr_labels, "ATR_NEG2")
        snap.atr_pos2 = pf(atr_labels, "ATR_POS2")
        snap.atr_neg3 = pf(atr_labels, "ATR_NEG3")
        snap.atr_pos3 = pf(atr_labels, "ATR_POS3")
        snap.lower_trig = pf(atr_labels, "LOWER_TRIG")
        snap.upper_trig = pf(atr_labels, "UPPER_TRIG")

        # IB Levels
        ib_labels = labels_for("JARVIS IB Levels")
        snap.ib_high = pf(ib_labels, "IB_HIGH")
        snap.ib_low = pf(ib_labels, "IB_LOW")
        snap.ib_range = pf(ib_labels, "IB_RANGE")
        snap.ib_mid = pf(ib_labels, "IB_MID")
        snap.ibu50 = pf(ib_labels, "IBU50")
        snap.ibu100 = pf(ib_labels, "IBU100")
        snap.ibd50 = pf(ib_labels, "IBD50")
        snap.ibd100 = pf(ib_labels, "IBD100")
        snap.ib_complete = pb(ib_labels, "IB_COMPLETE")

        # Composite Score
        comp_labels = labels_for("JARVIS Composite Score")
        snap.composite_score = pf(comp_labels, "COMPOSITE_SCORE")
        snap.regime = ps(comp_labels, "COMPOSITE_REGIME")
        snap.orb_high = pf(comp_labels, "ORB_HIGH")
        snap.orb_low = pf(comp_labels, "ORB_LOW")
        snap.vwap = pf(comp_labels, "VWAP")
        snap.vwap_upper = pf(comp_labels, "VWAP_UPPER")
        snap.vwap_lower = pf(comp_labels, "VWAP_LOWER")

        # Phase Oscillator
        phase_labels = labels_for("JARVIS Phase Oscillator")
        snap.phase_oscillator = pf(phase_labels, "PHASE_OSCILLATOR")
        snap.is_compressed = pb(phase_labels, "IS_COMPRESSED")
        snap.phase_state = ps(phase_labels, "PHASE_STATE")

        # Corey Score
        corey_labels = labels_for("JARVIS Corey Score")
        snap.corey_score = pf(corey_labels, "COREY_SCORE")
        snap.corey_bias = ps(corey_labels, "COREY_BIAS")
        # Volume reads from same indicator
        snap.vol_bull_pct = pf(corey_labels, "VOL_BULL_PCT")
        snap.vol_bear_pct = pf(corey_labels, "VOL_BEAR_PCT")
        snap.vol_bias = ps(corey_labels, "VOL_BIAS")

        # Pivot Points
        pivot_labels = labels_for("JARVIS Pivot Points")
        snap.pivot_pp = pf(pivot_labels, "PIVOT_PP")
        snap.pivot_r1 = pf(pivot_labels, "PIVOT_R1")
        snap.pivot_r2 = pf(pivot_labels, "PIVOT_R2")
        snap.pivot_r3 = pf(pivot_labels, "PIVOT_R3")
        snap.pivot_s1 = pf(pivot_labels, "PIVOT_S1")
        snap.pivot_s2 = pf(pivot_labels, "PIVOT_S2")
        snap.pivot_s3 = pf(pivot_labels, "PIVOT_S3")

        # Keltner
        kc_labels = labels_for("JARVIS Keltner OB Omega")
        snap.kc_upper = pf(kc_labels, "KC_UPPER")
        snap.kc_mid = pf(kc_labels, "KC_MID")
        snap.kc_lower = pf(kc_labels, "KC_LOWER")
        snap.kc_alignment = ps(kc_labels, "KC_ALIGNMENT")

        # Volume Profile
        vp_labels = labels_for("JARVIS Volume Profile")
        snap.vp_poc = pf(vp_labels, "VP_POC")
        snap.vp_vah = pf(vp_labels, "VP_VAH")
        snap.vp_val = pf(vp_labels, "VP_VAL")
        snap.vp_bias = ps(vp_labels, "VP_BIAS")

        # Gap Finder
        gap_labels = labels_for("JARVIS Gap Finder")
        snap.gap_exists = pb(gap_labels, "GAP_EXISTS")
        snap.gap_direction = ps(gap_labels, "GAP_DIRECTION")
        snap.gap_high = pf(gap_labels, "GAP_HIGH")
        snap.gap_low = pf(gap_labels, "GAP_LOW")
        snap.gap_filled = pb(gap_labels, "GAP_FILLED")

        # Market Cycle
        cycle_labels = labels_for("JARVIS Market Cycle")
        snap.cycle_phase = ps(cycle_labels, "CYCLE_PHASE")
        snap.cycle_score = pf(cycle_labels, "CYCLE_SCORE")

        # OTE Cloud
        ote_labels = labels_for("JARVIS OTE Cloud")
        snap.ote_bull_high = pf(ote_labels, "OTE_BULL_HIGH")
        snap.ote_bull_low = pf(ote_labels, "OTE_BULL_LOW")
        snap.ote_bear_high = pf(ote_labels, "OTE_BEAR_HIGH")
        snap.ote_bear_low = pf(ote_labels, "OTE_BEAR_LOW")
        snap.in_bull_ote = pb(ote_labels, "IN_BULL_OTE")
        snap.in_bear_ote = pb(ote_labels, "IN_BEAR_OTE")
        snap.mid_cloud = pf(ote_labels, "MID_CLOUD")

        # VPOC Tracker
        vpoc_labels = labels_for("JARVIS VPOC Tracker")
        snap.vpoc_today = pf(vpoc_labels, "VPOC_TODAY")
        snap.vpoc_yesterday = pf(vpoc_labels, "VPOC_YESTERDAY")
        snap.vpoc_delta = pf(vpoc_labels, "VPOC_DELTA")

        return snap

    # ------------------------------------------------------------------
    # Gamma-levels overlay parser
    # ------------------------------------------------------------------

    def _enrich_with_gamma(self, snapshot: TVIndicatorSnapshot) -> None:
        """
        Read "MY FREE GAMMA LEVELS" overlay labels (if present on the chart)
        and merge the 7 level values into `snapshot`. No-op when the vendor
        indicator is not loaded.
        """
        labels = self._read_labels(_GAMMA_FILTER)
        if not labels:
            return
        parsed = self._parse_gamma_levels(labels)
        for key, value in parsed.items():
            if value is not None:
                setattr(snapshot, key, value)

    @staticmethod
    def _parse_gamma_levels(labels: list) -> Dict[str, Optional[float]]:
        """
        Parse GEX flip, call/put walls, HVL, vol triggers, and max pain from
        the vendor's plotted labels. Label text format is not documented
        (closed script), so we match on case-insensitive substrings per
        `_GAMMA_ALIASES`. Each label contributes to at most one key; later
        labels do not overwrite earlier ones.

        Value resolution order per label:
          1. Label's numeric `price` field (chart y-axis coordinate) — preferred
          2. First float found in the label text — fallback when `price` absent
        """
        out: Dict[str, Optional[float]] = dict.fromkeys(_GAMMA_ALIASES)

        for label in labels:
            if not isinstance(label, dict):
                continue
            text_raw = label.get("text")
            if not isinstance(text_raw, str) or not text_raw.strip():
                continue
            text = text_raw.lower()

            # Figure out which key this label maps to (first alias match).
            matched_key: Optional[str] = None
            for key, aliases in _GAMMA_ALIASES.items():
                if out[key] is not None:
                    continue
                if any(alias in text for alias in aliases):
                    matched_key = key
                    break
            if matched_key is None:
                continue

            value = TVIndicatorBridge._coerce_label_value(label, text_raw)
            if value is not None:
                out[matched_key] = value
        return out

    @staticmethod
    def _coerce_label_value(label: dict, text_raw: str) -> Optional[float]:
        """Return numeric value of a label — prefer `price`, fall back to text."""
        price = label.get("price")
        if price is not None:
            try:
                return float(price)
            except (TypeError, ValueError):
                pass
        match = _NUM_RE.search(text_raw)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return None
        return None

    def reset(self) -> None:
        """Clear cache and availability state (call after TradingView restart)."""
        self._cache.clear()
        self._available = None
        self._manifest_available = None
        logger.debug("TVIndicatorBridge reset — availability and cache cleared")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bridge_instance: Optional[TVIndicatorBridge] = None


def get_tv_bridge() -> TVIndicatorBridge:
    """Return the shared TVIndicatorBridge singleton, creating it on first call."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = TVIndicatorBridge()
    return _bridge_instance
