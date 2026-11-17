"""Every migration must carry a stamp signature.

The startup hook re-adopts a persisted database by checking, per pending
migration, whether its signature object already exists - and stamping
instead of replaying the DDL. A migration that ships without a signature
opts out of that recovery: the day a volume outlives its version row, the
upgrade replays, and the database logs an "already exists" error on every
boot until someone stamps by hand. That is not hypothetical - 004..007
shipped unsigned and did exactly this.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import Any

import pytest

signatures_module = pytest.importorskip(
    "app.components.backend.startup.migration_signatures",
    reason="no database component in this stack",
)

VERSIONS = Path(__file__).parent.parent / "alembic" / "versions"


def _service_suffixes() -> list[str]:
    names = []
    for p in sorted(VERSIONS.glob("*.py")):
        m = re.match(r"\d+_(.+)", p.stem)
        if m:
            names.append(m.group(1))
    return names


def _revision_files() -> list[Path]:
    return [p for p in sorted(VERSIONS.glob("*.py")) if not p.name.startswith("__")]


def _retired_tables() -> set[str]:
    """Tables a later revision drops: what ``aegis remove-service`` retires.
    The service's own revisions stay, so its signature is history then."""
    return {
        name
        for p in _revision_files()
        for name in re.findall(r"""drop_table\(\s*["']([^"']+)["']""", p.read_text())
    }


PROVABLE = ("create_table(", "add_column(", "create_foreign_key(", "INSERT INTO")


def _has_something_to_prove(path: Path) -> bool:
    """Whether the revision makes something whose existence proves it ran.

    A created table, an added column, a new foreign key, an inserted row.
    A revision that only drops or re-indexes leaves nothing to check for,
    so the re-adoption hook has nothing to do with it either. Only
    ``upgrade()`` counts: the downgrade of a revision that drops a removed
    plugin's tables recreates them, and proves nothing about the upgrade.
    """
    source = path.read_text()
    upgrade = next(
        (
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
        ),
        None,
    )
    body = ast.get_source_segment(source, upgrade) or "" if upgrade else source
    return any(marker in body for marker in PROVABLE)


def _carried_signature(path: Path) -> tuple[str, ...] | None:
    """The signature a generated revision declares about itself."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign):
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "aegis_stamp_signature":
                value = ast.literal_eval(node.value)
                return tuple(value) if value is not None else None
    return None


def test_every_migration_file_has_a_stamp_signature() -> None:
    """Either the revision declares its own, or the legacy table names it.

    Revisions are derived from the models now, so a generated one carries
    the signature of the object it creates. The table stays for revisions
    written before that, which a long-lived project still has on disk.
    """
    signatures = signatures_module.SERVICE_MIGRATION_SIGNATURES
    missing = [
        path.name
        for path in _revision_files()
        if _has_something_to_prove(path)
        and _carried_signature(path) is None
        and (re.match(r"\d+_(.+)", path.stem) or [None, ""])[1] not in signatures
    ]
    assert not missing, (
        f"migrations without a stamp signature: {missing} - a generated "
        "revision declares `aegis_stamp_signature`; a hand-written one needs "
        "an entry in SERVICE_MIGRATION_SIGNATURES naming the table or column "
        "whose existence proves the migration ran"
    )


def test_a_carried_signature_names_something_the_revision_creates() -> None:
    """A signature that points outside its own revision can never fire."""
    for path in _revision_files():
        signature = _carried_signature(path)
        if signature is None:
            continue
        body = path.read_text()
        name = signature[1].split(".")[-1]
        assert f'"{name}"' in body or f"'{name}'" in body, (
            f"{path.name} claims {signature!r}, but never mentions {name}"
        )


def test_signatures_name_real_model_objects() -> None:
    """A signature pointing at a table nobody declares can never fire."""
    sqlmodel = pytest.importorskip(
        "sqlmodel", reason="stack has migrations dir but no ORM (e.g. worker-only)"
    )

    from app.core.model_registry import import_all_models

    # Every table registers the way alembic's env.py registers them.
    import_all_models()

    tables = set(sqlmodel.SQLModel.metadata.tables)
    bare = {t.split(".")[-1] for t in tables}
    installed = set(_service_suffixes())
    retired = _retired_tables()
    for service, sig in signatures_module.SERVICE_MIGRATION_SIGNATURES.items():
        if service not in installed:
            continue  # signature for a service this stack doesn't ship
        name = sig[1]
        if name.split(".")[-1] in retired:
            continue  # a removed service's: a later revision drops it
        assert name in tables or name in bare or name.split(".")[-1] in bare, (
            f"signature for '{service}' names '{name}', which no model declares"
        )


def test_row_signature_checks_the_live_database(tmp_path: Path) -> None:
    """``("row", table, where)``: the hook must replay a data-only revision
    whose row is missing and stamp it when the row is there."""
    already_applied = _hook().already_applied
    import sqlalchemy as sa

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'rows.db'}")
    with engine.begin() as conn:
        conn.execute(
            sa.text('CREATE TABLE "user" (id INTEGER PRIMARY KEY, email TEXT)')
        )
    signature = ("row", "user", "id = 0")
    assert already_applied(sa.inspect(engine), signature) is False
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO \"user\" VALUES (0, 'standalone@finance.local')")
        )
    assert already_applied(sa.inspect(engine), signature) is True
    # A table that does not exist is "not applied", never an exception.
    assert already_applied(sa.inspect(engine), ("row", "nope", "id = 0")) is False
    engine.dispose()


def test_data_only_revisions_use_the_row_form() -> None:
    """A data-only revision cannot be proven by a schema object."""
    sig = signatures_module.SERVICE_MIGRATION_SIGNATURES.get("finance_auth_link")
    if sig is None:
        pytest.skip("finance_auth_link not in this stack")
    assert sig[0] == "row" and sig[1] == "user" and "id = 0" in sig[2]


@pytest.mark.skipif(
    not (VERSIONS.parent / "alembic.ini").exists(),
    reason="this stack ships no migrations",
)
def test_the_startup_hook_can_read_a_carried_signature() -> None:
    """Alembic hands the hook the revision module; the constant rides on it.

    The hook reads ``rev.module.aegis_stamp_signature`` inside a broad
    try/except, so a broken mechanism would go unnoticed at boot: this is
    what fails instead.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic/alembic.ini"))
    carried = {
        rev.revision: getattr(rev.module, "aegis_stamp_signature", None)
        for rev in script.walk_revisions()
    }
    on_disk = {
        path.stem: _carried_signature(path)
        for path in _revision_files()
        if _carried_signature(path) is not None
    }
    if not on_disk:
        pytest.skip("no generated revisions in this project")
    assert any(carried.values()), (
        "revisions declare aegis_stamp_signature on disk, but alembic exposes "
        f"none of them to the startup hook: {sorted(on_disk)}"
    )


def _hook():  # type: ignore[no-untyped-def]
    """Steward's adoption hook (``startup.migrations``), or a skip."""
    pytest.importorskip("alembic", reason="no database component in this stack")
    return pytest.importorskip("app.components.backend.startup.migrations")


class TestSignatureMatching:
    """Every signature form is decided from the live schema."""

    def _inspector(self, tmp_path: Path):  # type: ignore[no-untyped-def]
        import sqlalchemy as sa

        engine = sa.create_engine(f"sqlite:///{tmp_path / 'forms.db'}")
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE org (id INTEGER PRIMARY KEY)"))
            conn.execute(
                sa.text(
                    'CREATE TABLE "user" (id INTEGER PRIMARY KEY, '
                    "org_id INTEGER REFERENCES org(id), locale TEXT)"
                )
            )
        return sa.inspect(engine)

    def test_table_form(self, tmp_path: Path) -> None:
        inspector, applied = self._inspector(tmp_path), _hook().already_applied
        assert applied(inspector, ("table", "public.user")) is True
        assert applied(inspector, ("table", "public.absent")) is False

    def test_column_form(self, tmp_path: Path) -> None:
        inspector, applied = self._inspector(tmp_path), _hook().already_applied
        assert applied(inspector, ("column", "public.user", "locale")) is True
        assert applied(inspector, ("column", "public.user", "nope")) is False

    def test_no_column_form(self, tmp_path: Path) -> None:
        """A migration that drops a column: proven by the column's absence,
        never by a table that is not there at all."""
        inspector, applied = self._inspector(tmp_path), _hook().already_applied
        assert applied(inspector, ("no_column", "public.user", "nope")) is True
        assert applied(inspector, ("no_column", "public.user", "locale")) is False
        assert applied(inspector, ("no_column", "absent", "locale")) is False

    def test_no_table_form(self, tmp_path: Path) -> None:
        """A migration that folds a table into another: proven by the old
        one's absence beside the one it went into, never by both absent."""
        inspector, applied = self._inspector(tmp_path), _hook().already_applied
        assert applied(inspector, ("no_table", "public.absent", "public.user"))
        assert applied(inspector, ("no_table", "org", "user")) is False
        assert applied(inspector, ("no_table", "absent", "also_absent")) is False

    def test_foreign_key_form(self, tmp_path: Path) -> None:
        inspector, applied = self._inspector(tmp_path), _hook().already_applied
        assert applied(inspector, ("foreign_key", "user", "org_id")) is True
        assert applied(inspector, ("foreign_key", "user", "locale")) is False


def _create(table: str) -> object:
    # alembic and sqlalchemy never share an import block: ruff counts alembic
    # as first-party only where an alembic/ folder exists, so a shared block
    # sorts one way before a database is added and the other way after.
    from alembic.operations import ops

    return ops.CreateTableOp(table, [_id_column()])


def _id_column() -> Any:
    import sqlalchemy as sa

    return sa.Column("id", sa.Integer, primary_key=True)


@pytest.fixture
def gen() -> object:
    """The revision generator; a stack without a database renders a stub."""
    pytest.importorskip("alembic", reason="no database component in this stack")
    return pytest.importorskip("app.cli.migrate_gen")


def test_the_signature_is_the_services_own_table_never_a_swept_one(
    gen: object,
) -> None:
    """A project older than a component's own migration hands that
    component's tables to whichever service is added next (the sweep).
    Signed by one of those tables, the revision would be stamped as done
    on boot, because the table already exists, and its own tables never
    created."""
    kept = [_create("apscheduler_jobs"), _create("blog_post")]
    assert gen._signature(kept, own_tables={"blog_post"}) == ("table", "blog_post")


def test_a_revision_with_no_table_of_its_own_still_signs(gen: object) -> None:
    assert gen._signature([_create("apscheduler_jobs")], own_tables=set()) == (
        "table",
        "apscheduler_jobs",
    )


def test_generated_signature_takes_precedence_over_legacy_service_entry() -> None:
    from types import SimpleNamespace

    from app.components.backend.startup.migrations import _signature_for_revision

    revision = SimpleNamespace(
        path="/tmp/038_ai.py",
        module=SimpleNamespace(
            aegis_stamp_signature=("column", "llm_usage", "duration_ms")
        ),
    )
    assert _signature_for_revision(revision, {"ai": ("table", "llm_org")}) == (
        "column",
        "llm_usage",
        "duration_ms",
    )
