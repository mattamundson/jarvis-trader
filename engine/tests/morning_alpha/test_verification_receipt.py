from morning_alpha.research.verification_receipt import (
    VerificationComponentEvidence,
    VerificationIdentity,
    VerificationStatus,
    build_verification_receipt,
)

H = "a" * 64


def identity(**updates):
    data = dict(
        code_commit="abc123",
        spec_version="v19.1",
        data_manifest_hash=H,
        candidate_population_hash="b" * 64,
        trial_ledger_hash="c" * 64,
        seeds={"bootstrap": 1, "placebo": 2},
    )
    data.update(updates)
    return VerificationIdentity(**data)


def component(name, status=VerificationStatus.VERIFIED, evidence_id=None):
    return VerificationComponentEvidence(
        name=name,
        status=status,
        evidence_id=evidence_id or (name[0] * 64),
    )


def test_all_verified_components_produce_verified_receipt():
    receipt = build_verification_receipt(
        identity(),
        (component("conformance"), component("red_team"), component("placebo"), component("execution")),
    )
    assert receipt.overall_status is VerificationStatus.VERIFIED
    assert len(receipt.receipt_id) == 64
    assert receipt.scipy_version
    assert receipt.numpy_version
    assert receipt.statsmodels_version


def test_failed_component_forces_failed_receipt():
    receipt = build_verification_receipt(identity(), (component("conformance", VerificationStatus.FAILED), component("red_team")))
    assert receipt.overall_status is VerificationStatus.FAILED


def test_incomplete_component_forces_incomplete_only_when_no_failure_exists():
    receipt = build_verification_receipt(identity(), (component("conformance"), component("execution", VerificationStatus.INCOMPLETE)))
    assert receipt.overall_status is VerificationStatus.INCOMPLETE


def test_evidence_identity_changes_receipt_id_but_presentation_summary_does_not():
    components = (component("conformance"), component("red_team"))
    a = build_verification_receipt(identity(), components, summary="first presentation")
    b = build_verification_receipt(identity(), components, summary="different wording")
    c = build_verification_receipt(identity(code_commit="different"), components, summary="first presentation")
    d = build_verification_receipt(identity(), (component("conformance", evidence_id="f"*64), component("red_team")))
    assert a.receipt_id == b.receipt_id
    assert a.receipt_id != c.receipt_id
    assert a.receipt_id != d.receipt_id


def test_empty_component_set_is_rejected():
    try:
        build_verification_receipt(identity(), ())
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("expected ValueError")
