"""Project-wide settings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SOURCE_DIR = DATA_DIR / "source"            # synthetic source data served by the fake API
CHECKPOINT_DIR = DATA_DIR / "checkpoints"   # one JSON watermark per brand x entity
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"
DBT_PROJECT_DIR = ROOT / "transform"

# Each brand is a tenant. reporting_tz is the timezone the brand reports its days in.
BRANDS = {
    "acme_apparel": {"reporting_tz": "America/New_York"},
    "bloom_skin": {"reporting_tz": "America/Los_Angeles"},
}

ENTITIES = ["customers", "sessions", "orders", "refunds", "ad_spend"]

# API client
PAGE_SIZE = 50
MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 0.1
LOAD_CHUNK_SIZE = 500

# Each incremental run re-reads this many days before the watermark, to pick up records
# that arrive late or get corrected after the fact. Ad platforms restate spend for a few
# days, so ad_spend gets the widest window.
LOOKBACK_DAYS = {
    "customers": 1,
    "sessions": 1,
    "orders": 3,
    "refunds": 3,
    "ad_spend": 7,
}
