"""
A fake paginated API that behaves like a slightly unreliable Shopify / ad-platform API.

Contract
--------
api.get_page(entity, cursor=None, updated_since=None, limit=50) -> dict

    returns {"data": [record, ...], "next_cursor": str | None}

    - returns the current version of each record, sorted by (updated_at, id)
    - updated_since is inclusive: records with updated_at >= updated_since
      (format "YYYY-MM-DDTHH:MM:SSZ", same as the records)
    - next_cursor is None on the last page
    - the cursor is opaque; pass back exactly what you received and keep entity and
      updated_since unchanged for every page of one pull
    - limit must be 1..250
    - like many offset-paginated APIs, a page occasionally repeats the last record of
      the previous page, so clients must tolerate duplicates

Errors (each has .status_code and .retryable)
    RateLimitError   429  retryable: wait .retry_after seconds, then retry the same call
    ServerError      503  retryable: back off, then retry the same call
    BadRequestError  400  not retryable: bad cursor, params or entity

as_of: the API only knows about records that had become available by this time.
       Moving as_of forward between runs simulates new, changed and late data arriving.
"""
import base64
import copy
import json
import random
import re
from pathlib import Path

import config

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class APIError(Exception):
    status_code = 0
    retryable = False


class RateLimitError(APIError):
    status_code = 429
    retryable = True

    def __init__(self, retry_after: float):
        super().__init__(f"429 Too Many Requests (retry after {retry_after}s)")
        self.retry_after = retry_after


class ServerError(APIError):
    status_code = 503
    retryable = True


class BadRequestError(APIError):
    status_code = 400
    retryable = False


class FakeAPI:
    def __init__(
        self,
        brand: str,
        as_of: str | None = None,
        rate_limit_prob: float = 0.08,
        server_error_prob: float = 0.04,
        duplicate_prob: float = 0.05,
        retry_after: float = 0.05,
        seed: int | None = 7,
        source_dir: Path | None = None,
    ):
        self.brand = brand
        self.as_of = as_of
        self.rate_limit_prob = rate_limit_prob
        self.server_error_prob = server_error_prob
        self.duplicate_prob = duplicate_prob
        self.retry_after = retry_after
        self.rng = random.Random(seed)
        self.calls = 0

        source_dir = source_dir or config.SOURCE_DIR
        self._versions = {}
        for entity in config.ENTITIES:
            path = source_dir / brand / f"{entity}.json"
            if not path.exists():
                raise FileNotFoundError(f"{path} is missing. Run: python -m source.generate")
            self._versions[entity] = json.loads(path.read_text())

    def get_page(self, entity: str, cursor: str | None = None,
                 updated_since: str | None = None, limit: int = config.PAGE_SIZE) -> dict:
        self.calls += 1

        if entity not in self._versions:
            raise BadRequestError(f"400 Bad Request: unknown entity {entity!r}")
        if not 1 <= limit <= 250:
            raise BadRequestError("400 Bad Request: limit must be 1..250")
        if updated_since is not None and not TIMESTAMP.match(updated_since):
            raise BadRequestError(f"400 Bad Request: bad updated_since {updated_since!r}")

        roll = self.rng.random()
        if roll < self.rate_limit_prob:
            raise RateLimitError(self.retry_after)
        if roll < self.rate_limit_prob + self.server_error_prob:
            raise ServerError("503 Service Unavailable")

        offset = 0
        if cursor is not None:
            state = self._decode(cursor)
            if state.get("e") != entity or state.get("s") != updated_since:
                raise BadRequestError("400 Bad Request: cursor does not match this query")
            offset = state["o"]

        rows = self._current_records(entity, updated_since)
        page = rows[offset: offset + limit]
        if offset > 0 and page and self.rng.random() < self.duplicate_prob:
            page = [rows[offset - 1]] + page

        has_more = offset + limit < len(rows)
        return {
            "data": copy.deepcopy(page),
            "next_cursor": self._encode(offset + limit, entity, updated_since) if has_more else None,
        }

    def _current_records(self, entity: str, updated_since: str | None) -> list[dict]:
        latest: dict[str, dict] = {}
        for version in self._versions[entity]:
            available_at = version.get("_available_at", version["updated_at"])
            if self.as_of is not None and available_at > self.as_of:
                continue
            current = latest.get(version["id"])
            if current is None or version["updated_at"] > current["updated_at"]:
                latest[version["id"]] = version

        rows = [
            {k: v for k, v in record.items() if not k.startswith("_")}
            for record in latest.values()
            if updated_since is None or record["updated_at"] >= updated_since
        ]
        rows.sort(key=lambda r: (r["updated_at"], r["id"]))
        return rows

    @staticmethod
    def _encode(offset: int, entity: str, updated_since: str | None) -> str:
        raw = json.dumps({"o": offset, "e": entity, "s": updated_since}).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def _decode(cursor: str) -> dict:
        try:
            return json.loads(base64.urlsafe_b64decode(cursor.encode()))
        except (ValueError, TypeError):
            raise BadRequestError("400 Bad Request: malformed cursor")
