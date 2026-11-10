"""The webserver builds the app's model of itself as it starts, in the
background, right after the health checks register: the first page that
draws it (a path card in chat, Overseer's map) does not wait on reading
the code, and the model is whole, not built partial and then again."""

from collections.abc import Coroutine
from typing import Any
from unittest.mock import patch

import pytest

from app.components.backend import background
from app.components.backend.startup import component_health
from app.core.ontology import system
from app.services.system import health

pytestmark = pytest.mark.usefixtures("app")


async def test_registering_the_checks_builds_the_model_behind_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: dict[str, Coroutine[Any, Any, None]] = {}
    built: list[bool] = []
    monkeypatch.setattr(
        background, "start", lambda name, work: started.setdefault(name, work)
    )
    monkeypatch.setattr(system, "current", lambda: built.append(system._registered()))
    with patch.dict(health._health_checks), patch.dict(health._service_health_checks):
        await component_health.startup_hook()
        await started["system_model"]

    assert built == [True]
