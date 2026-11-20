from datetime import UTC, datetime, timedelta

from morning_alpha.audit import ScorecardBuilder
from morning_alpha.cli import main
from morning_alpha.models import (
    MarketBar,
    OutcomeClassification,
    Session,
    SignalOutcome,
    StrategyKey,
)
from morning_alpha.providers import FakeMarketDataProvider
from morning_alpha.reporting import SECTION_ORDER, render_morning_report
from morning_alpha.service import MorningAlphaService, ScanStatus

AS_OF = datetime(2026, 9, 15, 13, 0, tzinfo=UTC)


class Detector:
    strategy = StrategyKey(strategy_id="report", version="1.0.0")

    def evaluate(self, snapshot, context):
        from morning_alpha.models import SetupCandidate

        return SetupCandidate(
            symbol=snapshot.symbol,
            strategy=self.strategy,
            as_of=snapshot.as_of,
            side="long",
            setup_type="relative_strength_breakout",
            thesis_code="R",
            proposed_entry=snapshot.price + 1,
            proposed_stop=snapshot.price - 1,
            theme="software",
        )

    def explain_features(self, snapshot, context):
        return {}


class Context:
    pass


def service(detectors=None):
    rows = []
    for i in range(20):
        ts = AS_OF - timedelta(days=19 - i)
        price = 100 + i
        rows.append(
            MarketBar(
                symbol="XYZ",
                timestamp=ts,
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1_000_000,
                session=Session.RTH,
                source="fixture",
                ingested_at=ts,
            )
        )
    return MorningAlphaService(
        provider=FakeMarketDataProvider({"XYZ": rows}),
        detectors=[Detector()] if detectors is None else detectors,
        context_builder=lambda snapshot: Context(),
    )


def test_report_sections_are_in_required_order():
    scan = service().scan(as_of=AS_OF, symbols=["XYZ"])
    prior = [
        SignalOutcome(
            symbol="XYZ",
            strategy=StrategyKey(strategy_id="report", version="1.0.0"),
            signal_as_of=AS_OF - timedelta(days=1),
            evaluated_as_of=AS_OF,
            triggered=False,
            classification=OutcomeClassification.FILTERED_LOSER,
        )
    ]
    score = ScorecardBuilder().build(prior)
    text = render_morning_report(scan, prior, score)
    positions = [text.index(section) for section in SECTION_ORDER]
    assert positions == sorted(positions)
    assert "[Inference] entry=" in text
    assert "NO TRADE | FILTERED_LOSER" in text


def test_no_trade_report_is_exact_machine_readable_token():
    scan = service(detectors=[]).scan(as_of=AS_OF, symbols=["XYZ"])
    assert scan.status is ScanStatus.NO_TRADE
    assert render_morning_report(scan) == "NO_TRADE"


def test_cli_scan_no_trade_exits_zero_and_prints_token(capsys):
    rc = main(
        [
            "scan",
            "--as-of",
            "2026-09-15T13:00:00Z",
            "--provider",
            "fake",
            "--symbols",
            "XYZ",
        ],
        service_factory=lambda args: service(detectors=[]),
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "NO_TRADE"


def test_cli_scan_json_is_machine_readable(capsys):
    rc = main(
        [
            "scan",
            "--as-of",
            "2026-09-15T13:00:00Z",
            "--provider",
            "fake",
            "--symbols",
            "XYZ",
            "--json",
        ],
        service_factory=lambda args: service(detectors=[]),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert '"status": "NO_TRADE"' in out


def test_cli_audit_and_trigger_lab_dispatch(capsys):
    assert main(
        ["audit", "--session", "2026-09-15"],
        audit_handler=lambda s: f"AUDIT {s}",
    ) == 0
    assert "AUDIT 2026-09-15" in capsys.readouterr().out
    assert main(
        ["research-trigger-lab", "--strategy", "x@1.0.0"],
        trigger_lab_handler=lambda s: f"LAB {s}",
    ) == 0
    assert "LAB x@1.0.0" in capsys.readouterr().out
