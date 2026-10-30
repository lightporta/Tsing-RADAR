"""DEBUG-only mentor simulation gate tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.main import app
from app.services import data_loader

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SIMULATION_PATH = BACKEND_ROOT / "data" / "mentors.simulation.json"
EMPTY_PATH = (
    BACKEND_ROOT.parent
    / "deploy"
    / "production"
    / "data"
    / "empty-mentor-governance.json"
)

client = TestClient(app)


def _clear_caches() -> None:
    data_loader.load_mentors.cache_clear()
    data_loader.load_match_candidates.cache_clear()
    data_loader.load_mentor_dataset.cache_clear()


@pytest.fixture(autouse=True)
def _restore_loader(monkeypatch):
    monkeypatch.setattr(data_loader, "_DATA_PATH", str(EMPTY_PATH))
    monkeypatch.setattr(
        data_loader, "_SIMULATION_DATA_PATH", str(SIMULATION_PATH)
    )
    monkeypatch.setattr(data_loader, "_simulation_enabled", lambda: False)
    _clear_caches()
    yield
    _clear_caches()


def test_default_mentors_remain_empty_and_formal():
    payload = client.get("/api/mentors").json()
    assert payload["data"] == []
    assert payload["meta"]["policy"] == data_loader.FORMAL_POLICY
    assert payload["meta"]["published_records"] == 0


def test_simulation_mentors_load_with_explicit_policy(monkeypatch):
    monkeypatch.setattr(data_loader, "_simulation_enabled", lambda: True)
    _clear_caches()

    payload = client.get("/api/mentors").json()
    assert len(payload["data"]) == 3
    assert payload["meta"]["policy"] == data_loader.SIMULATION_POLICY
    assert payload["meta"]["published_records"] == 3
    assert payload["meta"]["match_candidate_records"] == 3
    assert all(item["name"].startswith("【模拟】") for item in payload["data"])

    health = client.get("/health").json()
    assert health["llm_mode"] == "local_rules"
    # health uses live settings; simulation_mentors flag follows Settings, not
    # the loader monkeypatch. Mentor list above already proves simulation data.


def test_simulation_settings_rejected_outside_debug():
    with pytest.raises(ValidationError):
        Settings(
            ALLOW_SIMULATION_MENTORS=True,
            DEBUG=False,
            PRODUCTION_DEPLOYMENT=False,
        )
    with pytest.raises(ValidationError):
        Settings(
            ALLOW_SIMULATION_MENTORS=True,
            DEBUG=True,
            PRODUCTION_DEPLOYMENT=True,
        )


def test_health_exposes_local_rules_llm_mode():
    payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["llm_mode"] == "local_rules"
    assert payload["mentor_policy"] == data_loader.FORMAL_POLICY
    assert payload["simulation_mentors"] is False


@pytest.mark.parametrize(
    "debug,production,uses_fallback",
    [(True, False, True), (False, False, False), (True, True, False)],
)
def test_missing_formal_dataset_fallback_is_local_debug_only(
    monkeypatch, tmp_path, debug, production, uses_fallback
):
    missing = tmp_path / "missing-governance.json"
    monkeypatch.setattr(data_loader, "_DATA_PATH", str(missing))
    monkeypatch.setattr(settings, "DEBUG", debug)
    monkeypatch.setattr(settings, "PRODUCTION_DEPLOYMENT", production)
    if uses_fallback:
        assert data_loader.load_mentor_dataset().records == []
    else:
        with pytest.raises(FileNotFoundError):
            data_loader.load_mentor_dataset()
