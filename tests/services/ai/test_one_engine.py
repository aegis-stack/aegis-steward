"""The chat store and the usage ledger run on the async engine like every
other store in the app.

They were the last request-path code on the sync engine, and SQLite's
busy wait taken on the event loop froze a whole webserver (a downstream
app, 2026-09-16: Redis, the dashboard's SSE and the health check's own
HTTP call all timed out at once under a slow local-model turn). A
threadpool wrap was the emergency fix; one engine is the real one, and
this keeps it.
"""

import inspect

from app.services.ai.domains.chat import conversation
from app.services.ai.domains.llm import catalog
from app.services.ai.domains.spend import calls
from app.services.ai.domains.spend import recording as usage_recording
from app.services.ai.service import contexts, status, usage


def test_the_ai_store_never_opens_a_sync_session() -> None:
    modules = [conversation, catalog, usage, status, contexts]
    modules += [usage_recording, calls]
    for module in modules:
        source = inspect.getsource(module)
        assert "db_session" not in source, module.__name__
        assert "SessionLocal" not in source, module.__name__
        assert "run_in_threadpool" not in source, module.__name__
        assert "Session(engine)" not in source, module.__name__
