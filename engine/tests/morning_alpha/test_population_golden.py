from datetime import UTC, datetime, timedelta

from morning_alpha.models import MarketBar, Session
from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.candidate_store import CandidatePopulationWriter
from morning_alpha.research.population import HistoricalCandidatePopulationBuilder, HistoricalUniverseMember


def _bars(symbol,start,count,*,base,slope):
    rows=[]; day=start; i=0
    while len(rows)<count:
        if day.weekday()<5:
            close=base+i*slope
            rows.append(MarketBar(symbol=symbol,timestamp=day.replace(hour=20),open=close-.2,high=close+.6,low=close-.6,close=close,volume=1_500_000,session=Session.RTH,source="fixture",ingested_at=day.replace(hour=20,minute=1)))
            i+=1
        day+=timedelta(days=1)
    return rows


def _setup(manifest_hash="d"*64):
    start=datetime(2023,6,1,tzinfo=UTC)
    spy=_bars("SPY",start,252,base=400,slope=.25); xlk=_bars("XLK",start,252,base=180,slope=.30)
    qual=_bars("QUAL",start,252,base=100,slope=.70); reject=_bars("REJECT",start,252,base=100,slope=.10)
    decision=spy[-1].timestamp.replace(hour=13)+timedelta(days=1)
    while decision.weekday()>=5: decision+=timedelta(days=1)
    universe=(HistoricalUniverseMember(stable_security_id="SEC-Q",symbol="QUAL",sector="Technology",sector_etf="XLK",listing_timestamp=decision-timedelta(days=1000)),HistoricalUniverseMember(stable_security_id="SEC-R",symbol="REJECT",sector="Technology",sector_etf="XLK",listing_timestamp=decision-timedelta(days=1000)))
    ready=DataReadinessReport(ready=True,root="fixture",file_count=1,symbols=("QUAL","REJECT"),reasons=())
    return dict(readiness=ready,campaign_id="morning_alpha_v1",decision_timestamp=decision,data_manifest_hash=manifest_hash,universe=universe,bars_by_symbol={"QUAL":qual,"REJECT":reject},spy_bars=spy,sector_bars_by_etf={"XLK":xlk})


def test_golden_population_has_one_qualified_and_one_detector_reject():
    result=HistoricalCandidatePopulationBuilder().build_session(**_setup())
    assert result.input_universe_count==2
    assert result.qualified_count==1
    assert result.rejection_counts=={"DETECTOR_REJECTED":1}
    assert len(result.population_hash)==64


def test_future_contamination_does_not_change_prior_population():
    kwargs=_setup(); decision=kwargs["decision_timestamp"]; builder=HistoricalCandidatePopulationBuilder(); baseline=builder.build_session(**kwargs)
    future_ts=decision+timedelta(hours=8)
    for symbol in ("QUAL","REJECT"):
        kwargs["bars_by_symbol"][symbol]=kwargs["bars_by_symbol"][symbol]+[MarketBar(symbol=symbol,timestamp=future_ts,open=9999,high=10000,low=9998,close=9999,volume=99_000_000,session=Session.RTH,source="future",ingested_at=future_ts)]
    kwargs["spy_bars"]=kwargs["spy_bars"]+[MarketBar(symbol="SPY",timestamp=future_ts,open=9999,high=10000,low=9998,close=9999,volume=99_000_000,session=Session.RTH,source="future",ingested_at=future_ts)]
    kwargs["sector_bars_by_etf"]["XLK"]=kwargs["sector_bars_by_etf"]["XLK"]+[MarketBar(symbol="XLK",timestamp=future_ts,open=9999,high=10000,low=9998,close=9999,volume=99_000_000,session=Session.RTH,source="future",ingested_at=future_ts)]
    kwargs["universe"]=kwargs["universe"]+(HistoricalUniverseMember(stable_security_id="SEC-F",symbol="FUTURE",sector="Technology",sector_etf="XLK",listing_timestamp=decision+timedelta(days=1)),)
    again=builder.build_session(**kwargs)
    assert again.model_dump(mode="json")==baseline.model_dump(mode="json")


def test_manifest_and_split_identity_change_artifact_identity_without_changing_detector_shape(tmp_path):
    builder=HistoricalCandidatePopulationBuilder(); first=builder.build_session(**_setup("d"*64)); second=builder.build_session(**_setup("m"*64)); writer=CandidatePopulationWriter()
    a=writer.write(first,tmp_path/"a",code_commit="abc",split_registry_hash="s"*64); b=writer.write(second,tmp_path/"b",code_commit="abc",split_registry_hash="s"*64); c=writer.write(first,tmp_path/"c",code_commit="abc",split_registry_hash="x"*64)
    assert a.population_identity != b.population_identity
    assert a.population_identity != c.population_identity
    first_candidate=next(o for o in first.observations if o.detector_candidate is not None); second_candidate=next(o for o in second.observations if o.detector_candidate is not None)
    assert first_candidate.detector_candidate.model_dump(exclude={"features"}) == second_candidate.detector_candidate.model_dump(exclude={"features"})
