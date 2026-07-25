#!/usr/bin/env python
"""Export the FastAPI OpenAPI document to ``packages/shared-schemas``.

The exported document is the single source of truth for the frontend types.
CI regenerates it and fails when the committed copy drifts from the API.

Usage:
    uv run --project apps/api python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.main import create_app  # noqa: E402 - path set up above

OUTPUT = REPO_ROOT / "packages" / "shared-schemas" / "openapi.json"


def main() -> int:
    document = create_app().openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
