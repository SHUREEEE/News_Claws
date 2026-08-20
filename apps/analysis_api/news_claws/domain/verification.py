from __future__ import annotations

from dataclasses import dataclass

from news_claws.schemas import Confidence, VerificationStatus


@dataclass(frozen=True)
class EvidenceFact:
    evidence_id: str
    stance: str
    independence_group: str
    independence_known: bool
    quality: str
    primary_material: bool
    directly_observed: bool


@dataclass(frozen=True)
class VerificationDecision:
    status: VerificationStatus
    confidence: Confidence
    rationale: str
    supporting_ids: list[str]
    conflicting_ids: list[str]


def decide_verification(evidence: list[EvidenceFact]) -> VerificationDecision:
    supporting = [item for item in evidence if item.stance == "supports"]
    conflicting = [item for item in evidence if item.stance == "conflicts"]
    withdrawn = [item for item in evidence if item.stance in {"withdrawn", "disproves"}]

    if withdrawn:
        return VerificationDecision(
            VerificationStatus.WITHDRAWN_OR_DISPROVED,
            Confidence.HIGH
            if any(item.quality == "high" for item in withdrawn)
            else Confidence.MEDIUM,
            "已有撤回声明或直接证伪材料适用于该核心主张。",
            [item.evidence_id for item in supporting],
            [item.evidence_id for item in withdrawn],
        )

    if conflicting and supporting:
        return VerificationDecision(
            VerificationStatus.DISPUTED,
            Confidence.MEDIUM,
            "当前同时存在实质性支持证据与冲突证据，需并列审阅。",
            [item.evidence_id for item in supporting],
            [item.evidence_id for item in conflicting],
        )

    direct_primary = [
        item for item in supporting if item.primary_material and item.directly_observed
    ]
    if direct_primary:
        return VerificationDecision(
            VerificationStatus.PRIMARY_SOURCE_CONFIRMED,
            Confidence.HIGH,
            "适用的一手材料直接确认了可观察的发布或行动；材料中引用的其他主张不因此自动获得确认。",
            [item.evidence_id for item in supporting],
            [],
        )

    groups = {
        item.independence_group
        for item in supporting
        if item.independence_known and item.quality in {"medium", "high"}
    }
    if len(groups) >= 2:
        return VerificationDecision(
            VerificationStatus.MULTI_SOURCE_CORROBORATED,
            Confidence.HIGH if len(groups) >= 3 else Confidence.MEDIUM,
            f"已有 {len(groups)} 条可审计且相互独立的信息链一致支持该核心主张。",
            [item.evidence_id for item in supporting],
            [],
        )

    return VerificationDecision(
        VerificationStatus.SINGLE_SOURCE_REPORTED,
        Confidence.LOW if not supporting else Confidence.MEDIUM,
        "该主张目前只有一条已确认信息链，或来源独立性未知；系统不据此推断未经校准的真实性概率。",
        [item.evidence_id for item in supporting],
        [],
    )
