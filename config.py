"""Project-wide settings. Boilerplate: safe to edit."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SOURCE_DIR = DATA_DIR / "source"            # synthetic "API" data lives here
CHECKPOINT_DIR = DATA_DIR / "checkpoints"   # one JSON file per brand x entity
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"

# Each brand is a tenant. reporting_tz is the timezone the brand reports its days in.
BRANDS = {
    "acme_apparel": {"reporting_tz": "America/New_York"},
    "bloom_skin": {"reporting_tz": "America/Los_Angeles"},
}

ENTITIES = ["customers", "sessions", "orders", "refunds", "ad_spend"]

PAGE_SIZE = 50
