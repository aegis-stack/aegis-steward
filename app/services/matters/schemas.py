"""What the matter tools return, as types.

Code mode prints each tool's return type in the signature the model
codes against (``finance.schemas.agent_tools`` says why): typed
``dict[str, Any]``, her scripts guessed keys. A key lives here once.
Each ``*_cents`` number also arrives with its ``*_usd`` beside it
(``with_dollars``, after the tool returns, so declared NotRequired).
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from app.services.finance.schemas.agent_tools import Charges


class NotFound(TypedDict):
    error: str  # the id names nothing on file


class Relation(TypedDict):
    relation: str  # "spouse of", "parent of", "child of", "related to"
    party_id: int
    party: str | None


class PartyRow(TypedDict):
    id: int
    name: str
    kind: str  # "person" | "organization"
    sort_name: str
    contact: dict[str, Any]
    note: str | None
    document_ids: list[int]
    policy_ids: list[int]
    covered_by_policy_ids: list[int]
    transactions: Charges
    relations: list[Relation]


class Parties(TypedDict):
    parties: list[PartyRow]


class Participant(TypedDict):
    role: str
    party_id: int
    party: str


class RequestCounts(TypedDict):
    open: int
    total: int
    next_due: str | None
    overdue_count: int


class MatterRow(TypedDict):
    id: int
    title: str
    kind: str | None
    reference: str | None
    note: str | None
    status: str
    opened_on: str | None
    subject: str | None
    counterpart: str | None
    participants: list[Participant]
    requests: RequestCounts
    transactions: Charges
    documents: int  # how many are filed on it


class Matters(TypedDict):
    matters: list[MatterRow]


class AskedItem(TypedDict):
    id: int
    ordinal: int
    asked: str  # as written: the wording we are held to
    ask: str | None
    as_of: str | None
    status: str
    resolution: str | None
    document_id: int | None  # the paper that answers it


class RequestRow(TypedDict):
    id: int
    matter_id: int
    matter: str | None
    letter_document_id: int | None
    letter: str | None
    received_on: str | None
    due_on: str | None
    status: str
    overdue: bool
    settled: int
    total: int
    note: str | None
    items: list[AskedItem]


class Requests(TypedDict):
    requests: list[RequestRow]


class FactRow(TypedDict):
    id: int
    subject_party_id: int
    subject: str | None
    matter_id: int | None
    account_id: int | None
    attribute: str
    attribute_label: str | None
    label: str | None
    value_cents: int | None
    value_usd: NotRequired[str]
    period: str  # "once" | "day" | "week" | "month" | "year"
    monthly_cents: int | None
    monthly_usd: NotRequired[str]
    text_value: str | None
    as_of: str | None
    provenance: str  # "stated" | "document" | "ledger"
    document_id: int | None
    page: int | None
    source_note: str | None
    source_url: str | None
    verified: bool
    note: str | None


class Facts(TypedDict):
    facts: list[FactRow]


class DocumentText(TypedDict):
    id: int
    title: str
    kind: str
    media_type: str | None
    page_count: int | None
    dated: str | None
    read: bool
    reading: str | None  # the job id, only while still on the worker
    text: str  # each page under '--- page N ---'
    figures: dict[str, Any]


class Sender(TypedDict):
    party_id: int
    name: str


# Functional: its 'from' key is a Python keyword.
ShelfRow = TypedDict(
    "ShelfRow",
    {
        "id": int,
        "title": str,
        "kind": str,
        "form_type": str | None,
        "tax_year": int | None,
        "document_date": str | None,
        "pages": int | None,
        "figures": dict[str, Any],
        "from": list[Sender],
    },
)


class Shelf(TypedDict):
    documents: list[ShelfRow]


class WebOffer(TypedDict):
    field: str
    label: NotRequired[str]
    value: str
    url: str
    source: str  # put in 'sources' exactly as given


class WebLookup(TypedDict):
    confirmed: str | None
    found_by: str | None  # "guess" | "search"
    offers: list[WebOffer]
    corroborated_against: list[str]


class PaperOffer(TypedDict):
    field: str  # address | phone | email | website, or labelled lines
    label: NotRequired[str]
    value: str
    document_id: int
    page: int


class ContactDetails(TypedDict):
    party_id: int
    name: str
    offers: list[PaperOffer]
