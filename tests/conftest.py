"""Test wiring: point the app at a throwaway SQLite DB before it's imported."""
from __future__ import annotations

import os
import tempfile

# Must run before `app.config` is imported anywhere.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["WEBHOOK_TOKEN"] = "test-token"
os.environ.setdefault("SHEET_CSV_URL", "./sample_data/builder_updates.csv")
