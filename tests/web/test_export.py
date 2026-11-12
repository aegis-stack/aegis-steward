"""Export everything (#623): the whole ledger as the archive ``finance
export`` writes, built off the request and handed back as a download."""

import gzip
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from tests.web.conftest import HX, Ledger, follow
from tests.web.dom import one
from tests.web.overseer import sign_in, status_with


def test_activity_offers_export_everything(client: TestClient) -> None:
    button = one(client.get("/settings/activity").text, "[data-export-everything]")
    assert button.get("hx-post") == "/settings/export"
    assert button.get("hx-target") == "#dialog-body"


def test_the_export_runs_as_a_job_and_downloads_the_archive(
    live_client: TestClient, ledger: Ledger, job_session: None
) -> None:
    started = live_client.post("/settings/export", headers=HX)
    _, final = follow(live_client, started.text)
    link = one(final, "a[data-export-download]")

    archive = live_client.get(link.get("href") or "")

    assert archive.status_code == 200
    assert "attachment" in archive.headers["content-disposition"]
    lines = gzip.decompress(archive.content).decode().splitlines()
    assert json.loads(lines[0])["format"]
    tables = {json.loads(line)["table"] for line in lines[1:]}
    assert "finance_account" in tables
    # A copy of the whole ledger is not left lying in storage.
    assert live_client.get(link.get("href") or "").status_code == 404


@pytest.mark.parametrize(
    ("method", "path"), [("POST", "/settings/export"), ("GET", "/settings/export/x")]
)
def test_a_member_cannot_export(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    from app.services.auth.deps import get_current_active_user

    member = sign_in(app, monkeypatch, status_with(), admin=False)
    app.dependency_overrides[get_current_active_user] = lambda: member
    assert TestClient(app).request(method, path).status_code == 403


async def test_the_download_serves_only_an_export(client: TestClient) -> None:
    """It names a storage key, so it must not hand out a receipt or an
    upload that happens to live there too."""
    from app.core.storage import get_storage

    key = await get_storage().put(b"a receipt, not an export")

    assert client.get(f"/settings/export/{key}").status_code == 404
