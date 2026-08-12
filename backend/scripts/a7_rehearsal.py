"""Run an isolated, synthetic, local-only A7 competition rehearsal."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    repository_root = Path(__file__).resolve().parents[2]
    backend_root = repository_root / "backend"
    with tempfile.TemporaryDirectory(prefix="tsing-radar-a7-") as temp_root:
        temp_path = Path(temp_root)
        os.environ.update(
            {
                "DATABASE_URL": f"sqlite:///{(temp_path / 'a7.db').as_posix()}",
                "PRIVATE_UPLOAD_ROOT": str(temp_path / "private"),
                "OBJECT_STORAGE_LOCAL_ROOT": str(temp_path / "objects"),
                "OBJECT_STORE_BACKEND": "local",
                "FILE_SCAN_MODE": "builtin",
                "DEBUG": "true",
                "QXD_API_KEY": "a7-local-platform-key",
                "QXD_END_USER_SIGNING_SECRET": (
                    "a7-local-end-user-signing-secret"
                ),
                "PUBLIC_BASE_URL": "",
                "ALLOW_TEST_PUBLIC_BASE_URL": "false",
                "GLM_API_KEY": "",
                "DEEPSEEK_API_KEY": "",
            }
        )
        sys.path.insert(0, str(backend_root))
        from fastapi.testclient import TestClient

        from app.services import data_loader
        tracked_empty_seed = (
            repository_root
            / "deploy"
            / "production"
            / "data"
            / "empty-mentor-governance.json"
        )
        if not tracked_empty_seed.is_file():
            raise RuntimeError("tracked_empty_mentor_governance_seed_missing")
        data_loader._DATA_PATH = str(tracked_empty_seed)

        from app.main import app
        from app.db.session import engine
        from app.services.rehearsal import (
            compact_rehearsal_json,
            run_local_competition_rehearsal,
        )

        with TestClient(app) as client:
            report = run_local_competition_rehearsal(
                client,
                qxd_platform_key="a7-local-platform-key",
                qxd_claim_secret="a7-local-end-user-signing-secret",
            )
        engine.dispose()
        print(compact_rehearsal_json(report))
        return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
