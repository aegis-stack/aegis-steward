"""How one run that brought data in reads: what to call it, what it
brought, and what state it is in. A list of runs (Settings > Activity),
a single run's dialog and the CLI all read these, so the same row is never
named two ways.
"""

from __future__ import annotations

from typing import Any

from app.services.finance.constants import PROVIDER_LABELS, sync_source

# What a source is CALLED where a person reads it. The stored value is
# the machine's word (``snaptrade_sync``, ``csv``), constrained by the
# batch table itself; this is the answer to "where did this come from",
# which is the question actually being asked.
SOURCE_LABELS: dict[str, str] = {
    **{sync_source(key): label for key, label in PROVIDER_LABELS.items()},
    "csv": "CSV",
    "ofx": "OFX",
    "qfx": "QFX",
    "qif": "QIF",
    "manual": "By hand",
}


def run_title(batch: Any) -> str:
    """What to call one run: where it came from, and the file if it had
    one. Beside ``run_summary`` because a list of runs and a single run
    must not name the same row two ways."""
    source = getattr(batch, "source_type", "") or ""
    named = SOURCE_LABELS.get(source, source)
    file_name = getattr(batch, "file_name", None)
    return f"{named} · {file_name}" if file_name else named


# What a run is counted in, in the order a reader wants it. The counts a
# FILE has live on the batch; the ones only a provider has (holdings,
# trades) ride in ``detail`` - which is the whole reason ``detail`` is a
# JSON column and not five more.
RUN_COUNTS: tuple[tuple[str, str], ...] = (
    ("rows_inserted", "new"),
    ("rows_updated", "updated"),
    ("holdings", "holdings"),
    ("trades", "trades"),
    ("rows_duplicate", "duplicate"),
    ("rows_error", "failed"),
)


def run_summary(batch: Any) -> str:
    """What one run actually brought, in its own terms.

    A file counts rows; a brokerage counts holdings and trades. Reading
    "0 transactions" off a sync that restated ten positions is how a
    working import gets reported as broken, so each source answers in the
    units it deals in.

    Here, not in a page: the Activity list, a run dialog and the CLI must
    not each word the same five numbers their own way.
    """
    detail = getattr(batch, "detail", None) or {}
    said = [
        f"{count} {word}"
        for attr, word in RUN_COUNTS
        for count in [getattr(batch, attr, None) or detail.get(attr) or 0]
        if count
    ]
    if said:
        return " · ".join(said)
    # A run that brought nothing is the most interesting kind, so it says
    # so rather than rendering an empty cell; a failed one says why (#532).
    if getattr(batch, "status", "") == "committed":
        return "nothing"
    return (getattr(batch, "error", None) or "-").splitlines()[0]


# A run's state as a status chip. "rolled_back" is a choice (#621), not a
# failure, so it does not wear the error tone.
RUN_STATES: dict[str, tuple[str, str]] = {
    "committed": ("committed", "ok"),
    "rolled_back": ("undone", "muted"),
}


def run_state(batch: Any) -> dict[str, str]:
    status = getattr(batch, "status", "") or ""
    label, tone = RUN_STATES.get(status, (status, "error"))
    return {"label": label, "tone": tone}
