"""Seed rows: insert what is missing by key, never touch what is there.

Startup seeds (currencies, import profiles, agents, memory modules, tool
rows) all share one rule: a row whose key is already present is left
alone, because everything seeded is editable afterwards and a reboot must
not undo that. One query finds what is present; the rest is added.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement
from sqlmodel import Session, SQLModel, col, select


def missing_rows(
    session: Session,
    model: type[SQLModel],
    key: str | tuple[str, ...],
    rows: Sequence[dict[str, Any]],
    *where: ColumnElement[bool],
) -> list[dict[str, Any]]:
    """The rows whose ``key`` value is not yet in ``model``'s table, each
    key once. A key of several columns (a link row's pair) is matched whole.

    ``where`` narrows what counts as present (system import profiles share
    names with user-owned ones, so only ownerless rows count).
    """
    keys = (key,) if isinstance(key, str) else key
    columns = [col(getattr(model, name)) for name in keys]
    wanted: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        wanted.setdefault(tuple(row[name] for name in keys), row)
    narrowed = [
        column.in_({values[i] for values in wanted}) for i, column in enumerate(columns)
    ]
    found = session.exec(select(*columns).where(*narrowed, *where)).all()
    present = {tuple(row) if len(keys) > 1 else (row,) for row in found}
    return [row for values, row in wanted.items() if values not in present]


def seed_rows(
    session: Session,
    model: type[SQLModel],
    key: str | tuple[str, ...],
    rows: Sequence[dict[str, Any]],
    *where: ColumnElement[bool],
) -> int:
    """Add the missing rows (see ``missing_rows``); the caller commits."""
    missing = missing_rows(session, model, key, rows, *where)
    session.add_all([model(**row) for row in missing])
    return len(missing)
