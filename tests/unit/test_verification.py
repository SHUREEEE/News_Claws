from news_claws.domain.verification import EvidenceFact, decide_verification
from news_claws.schemas import VerificationStatus


def item(
    evidence_id: str,
    group: str,
    *,
    stance: str = "supports",
    primary: bool = False,
    direct: bool = False,
    known: bool = True,
) -> EvidenceFact:
    return EvidenceFact(
        evidence_id=evidence_id,
        stance=stance,
        independence_group=group,
        independence_known=known,
        quality="high",
        primary_material=primary,
        directly_observed=direct,
    )


def test_reposts_do_not_become_independent_corroboration() -> None:
    decision = decide_verification([item("ev_1", "wire_a"), item("ev_2", "wire_a")])
    assert decision.status == VerificationStatus.SINGLE_SOURCE_REPORTED


def test_unknown_independence_is_not_counted_optimistically() -> None:
    decision = decide_verification([item("ev_1", "a"), item("ev_2", "unknown", known=False)])
    assert decision.status == VerificationStatus.SINGLE_SOURCE_REPORTED


def test_primary_material_confirms_only_direct_observation() -> None:
    indirect = decide_verification([item("ev_1", "official", primary=True, direct=False)])
    direct = decide_verification([item("ev_1", "official", primary=True, direct=True)])
    assert indirect.status == VerificationStatus.SINGLE_SOURCE_REPORTED
    assert direct.status == VerificationStatus.PRIMARY_SOURCE_CONFIRMED


def test_conflicting_high_quality_evidence_is_disputed() -> None:
    decision = decide_verification([item("ev_1", "a"), item("ev_2", "b", stance="conflicts")])
    assert decision.status == VerificationStatus.DISPUTED
    assert decision.conflicting_ids == ["ev_2"]
