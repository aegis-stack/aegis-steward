"""What the insurance tools return, as types (see ``matters.schemas``)."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from app.services.finance.schemas.agent_tools import Charge


class ClaimRow(TypedDict):
    id: int
    covered_party_id: int
    service_on: str | None
    provider_party_id: int | None
    claim_number: str | None
    status: str
    billed_cents: int
    billed_usd: NotRequired[str]
    allowed_cents: int
    allowed_usd: NotRequired[str]
    insurer_paid_cents: int
    insurer_paid_usd: NotRequired[str]
    patient_owes_cents: int
    patient_owes_usd: NotRequired[str]
    document_id: int | None  # readable with `paper`
    paid_transaction_id: int | None


class PolicyRow(TypedDict):
    id: int
    insurer_party_id: int
    insurer: str | None
    covered_party_ids: list[int]
    kind: str
    name: str | None
    policy_number: str | None
    member_id: str | None
    group_id: str | None
    effective_on: str | None
    renews_on: str | None
    premium_stream_id: int | None
    terms: dict[str, Any]
    patient_owes_cents: int
    patient_owes_usd: NotRequired[str]
    claims: list[ClaimRow]


class Policies(TypedDict):
    policies: list[PolicyRow]


class ClaimCandidates(TypedDict):
    claim_id: int
    candidates: list[Charge]  # each 'id' is what claim.paid takes
