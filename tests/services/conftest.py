"""Shared fixtures for the service-layer suite."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService
from tests._session import opens


@pytest.fixture
async def svc(async_db_session: AsyncSession) -> FinanceService:
    """The finance service under test.

    One construction site for ~450 tests: when FinanceService grows a
    constructor argument, this is the only line that changes.
    """
    return FinanceService(async_db_session)


@pytest.fixture
def open_session(async_db_session: AsyncSession):
    """For code that takes a way to OPEN a database (the mail ingest, a
    pull): the per-test session, never committed."""
    return opens(async_db_session)
