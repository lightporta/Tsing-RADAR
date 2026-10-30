"""Exercise the documented local preset in a clean process, without cloud APIs."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine

from app.core.config import Settings


ROOT = Path(__file__).resolve().parents[2]


def test_copied_development_example_starts_with_synthetic_local_resources(tmp_path):
    (tmp_path / ".env").write_bytes((ROOT / "backend/.env.example").read_bytes())
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in Settings.model_fields
        and not key.startswith("MENTOR_DATA_EXPECTED_")
    }
    environment["PYTHONPATH"] = str(ROOT / "backend")
    script = """
import json
from fastapi.testclient import TestClient
from app.main import app
from app.services.data_loader import load_mentors
from app.services.object_storage import get_object_store, LocalPrivateObjectStore
with TestClient(app) as client:
    health = client.get('/health').json()
    assert health['llm_mode'] == 'local_rules'
    assert health['simulation_mentors'] is True
    assert len(load_mentors()) == 3
    assert isinstance(get_object_store(), LocalPrivateObjectStore)
    print(json.dumps({'status': 'passed', 'mentor_count': len(load_mentors())}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mentor_count"] == 3


def test_local_compose_database_urls_load_installed_driver_without_connecting():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    urls = re.findall(r"^\s+DATABASE_URL: (.+)$", compose, re.MULTILINE)
    assert len(urls) == 2  # migration and backend share a driver contract
    for url in urls:
        engine = create_engine(url)
        assert engine.dialect.driver == "psycopg"
        engine.dispose()
    assert "condition: service_completed_successfully" in compose
    assert "empty-mentor-governance.json:/app/data/mentors.evidence.json:ro" in compose
    assert "mentors.simulation.json:/app/data/mentors.simulation.json:ro" in compose


def test_empty_optional_provider_means_local_rules():
    assert Settings(_env_file=None, LLM_PROVIDER="").llm_mode == "local_rules"


def test_isolated_rehearsal_ignores_the_development_dotenv(tmp_path):
    (tmp_path / ".env").write_bytes((ROOT / "backend/.env.example").read_bytes())
    result = subprocess.run(
        [sys.executable, str(ROOT / "backend/scripts/a7_rehearsal.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "passed"
    assert report["safety"]["network_requests_performed"] is False
    assert report["safety"]["real_credentials_used"] is False
