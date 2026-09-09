import sys
from pathlib import Path

# Makes `import app...` resolve regardless of the working directory pytest was
# invoked from (repo root, backend/, or backend/tests/) - simpler and more robust
# than relying on pytest's own rootdir/import-mode detection for a non-package
# tests/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app import db  # noqa: E402


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """A fresh, fully-initialized (DDL + seeded dims) SQLite warehouse in a temp
    file - never the real backend/data/warehouse.db. db.get_connection() always
    reads the module-level DB_PATH, so monkeypatching it here is enough to redirect
    every db.py function under test without changing their signatures."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_warehouse.db")
    db.init_db()
    connection = db.get_connection()
    yield connection
    connection.close()
