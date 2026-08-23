"""Run the A7 read-only offline deployment preflight."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.preflight import run_offline_preflight  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print blockers but return zero; never changes the report status.",
    )
    args = parser.parse_args()
    report = run_offline_preflight(settings, repository_root=REPOSITORY_ROOT)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["status"] != "ready" and not args.report_only:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
