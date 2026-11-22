"""079: whether a model calls tools lives on its deployment alone.

The catalog said it twice: the deployment's ``function_calling`` (the
cloud sync's) and 077's ``supports_tools`` on the model (the local
sync's), and the Thinks list read the copy the cloud sync never filled
(2026-11-22). 079 moves a local model's word onto its deployment and
drops the copy."""

from pathlib import Path
import sqlite3

from alembic import command


def test_the_models_copy_moves_onto_its_deployment_and_goes(
    tmp_path: Path,
) -> None:
    from app.components.backend.startup import migrations

    db = tmp_path / "catalog.db"
    config = migrations._alembic_config(migrations._url_for(str(db)))
    command.upgrade(config, "078")
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "INSERT INTO llm_org (id, slug, name, color, icon_path, auth_method,"
            " source, created_at) VALUES (1, 'ollama', 'ollama', '', '', 'none',"
            " 'local', '2026-11-22')"
        )
        models = {1: ("cloud", True), 2: ("local", True), 3: ("unsaid", None)}
        for id_, (name, tools) in models.items():
            connection.execute(
                "INSERT INTO large_language_model (id, model_id, title, description,"
                " context_window, training_data, streamable, enabled, color,"
                " icon_path, mode, served_by_org_id, supports_tools)"
                " VALUES (?, ?, ?, '', 0, '', 1, 1, '', '', 'chat', 1, ?)",
                (id_, name, name, tools),
            )
        connection.execute(
            "INSERT INTO llm_deployment (llm_id, org_id, speed, intelligence,"
            " reasoning, output_max_tokens, function_calling, input_cache,"
            " structured_output) VALUES (1, 1, 50, 50, 50, 8192, 1, 0, 0)"
        )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(config, "079")

    connection = sqlite3.connect(db)
    try:
        deployed = connection.execute(
            "SELECT m.model_id, d.function_calling, d.output_max_tokens"
            " FROM llm_deployment d JOIN large_language_model m ON m.id = d.llm_id"
        ).fetchall()
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(large_language_model)")
        }
    finally:
        connection.close()
    assert sorted(deployed) == [("cloud", 1, 8192), ("local", 1, 4096)]
    assert "supports_tools" not in columns
