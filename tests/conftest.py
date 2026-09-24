import json
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from source.fake_api import FakeAPI  # noqa: E402

BRAND = "test_brand"


def record(record_id: str, updated_at: str, **extra) -> dict:
    return {"id": record_id, "updated_at": updated_at, **extra}


@pytest.fixture
def tmp_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SOURCE_DIR", tmp_path / "source")
    monkeypatch.setattr(config, "CHECKPOINT_DIR", tmp_path / "checkpoints")
    return tmp_path


@pytest.fixture
def make_api(tmp_paths):
    """Write the given entity data to a temp source dir and return a reliable FakeAPI over it."""
    def _make(as_of=None, **entities):
        brand_dir = config.SOURCE_DIR / BRAND
        brand_dir.mkdir(parents=True, exist_ok=True)
        for entity in config.ENTITIES:
            (brand_dir / f"{entity}.json").write_text(json.dumps(entities.get(entity, [])))
        return FakeAPI(BRAND, as_of=as_of, rate_limit_prob=0, server_error_prob=0, duplicate_prob=0)
    return _make


@pytest.fixture
def con():
    connection = duckdb.connect()
    yield connection
    connection.close()
