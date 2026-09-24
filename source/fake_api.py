"""
A fake paginated API that behaves like a slightly unreliable Shopify / ad-platform API.

BOILERPLATE: written for you. This is the server side. Your ingestion code is the client.
Read the contract below carefully; your client is built on it, not on guesses.

THE CONTRACT
------------
api.get_page(entity, cursor=None, updated_since=None, limit=50) -> dict

    returns {"data": [record, ...], "next_cursor": str | None}

    - records are sorted by (updated_at, id) ascending
    - updated_since is INCLUSIVE: you get records with updated_at >= updated_since
      (format "YYYY-MM-DDTHH:MM:SSZ", same as the records)
    - next_cursor is None on the last page
    - the cursor is opaque: pass back exactly what you received. Never build one yourself,
      and keep entity + updated_since the same for every page of one pull
    - limit must be 1..250

ERRORS (each has .status_code and .retryable)
    RateLimitError   429  retryable: wait e.retry_after seconds, then retry the SAME call
    ServerError      503  retryable: back off exponentially, then retry the SAME call
    BadRequestError  400  FATAL: bad cursor / params / unknown entity. Retrying never helps.

as_of: the API only knows about records with updated_at <= as_of.
       Move as_of forward between runs to simulate new data arriving.
"""
import base64
import copy
import json
import random
import re

import config

TS_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class APIError(Exception):
    status_code = 0
    retryable = False


class RateLimitError(APIError):
    status_code = 429
    retryable = True

    def __init__(self, retry_after: float):
        super().__init__(f"429 Too Many Requests (Retry-After: {retry_after}s)")
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
        retry_after: float = 0.2,
        seed: int | None = 7,
    ):
        if brand not in config.BRANDS:
            raise ValueError(f"unknown brand {brand!r}")
        self.brand = brand
        self.as_of = as_of
        self.rate_limit_prob = rate_limit_prob
        self.server_error_prob = server_error_prob
        self.retry_after = retry_after
        self.rng = random.Random(seed)
        self.calls = 0  # handy for tests: how many requests did the client make?
        self._data = {}
        for entity in config.ENTITIES:
            path = config.SOURCE_DIR / brand / f"{entity}.json"
            if not path.exists():
                raise FileNotFoundError(f"{path} missing. Run: python -m source.generate")
            self._data[entity] = json.loads(path.read_text())

    # --- cursor helpers (opaque to the client) ---------------------------------
    @staticmethod
    def _encode(offset: int, entity: str, updated_since: str | None) -> str:
        raw = json.dumps({"o": offset, "e": entity, "s": updated_since}).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @staticmethod
    def _decode(cursor: str) -> dict:
        try:
            return json.loads(base64.urlsafe_b64decode(cursor.encode()))
        except Exception:
            raise BadRequestError("400 Bad Request: malformed cursor")

    # --- the endpoint ------------------------------------------------------------
    def get_page(self, entity: str, cursor: str | None = None,
                 updated_since: str | None = None, limit: int = config.PAGE_SIZE) -> dict:
        self.calls += 1

        if entity not in self._data:
            raise BadRequestError(f"400 Bad Request: unknown entity {entity!r}")
        if not 1 <= limit <= 250:
            raise BadRequestError("400 Bad Request: limit must be 1..250")
        if updated_since is not None and not TS_FORMAT.match(updated_since):
            raise BadRequestError(f"400 Bad Request: bad updated_since {updated_since!r}")

        roll = self.rng.random()
        if roll < self.rate_limit_prob:
            raise RateLimitError(self.retry_after)
        if roll < self.rate_limit_prob + self.server_error_prob:
            raise ServerError("503 Service Unavailable")

        offset = 0
        if cursor is not None:
            c = self._decode(cursor)
            if c.get("e") != entity or c.get("s") != updated_since:
                raise BadRequestError("400 Bad Request: cursor does not match this query")
            offset = c["o"]

        rows = [r for r in self._data[entity]
                if (self.as_of is None or r["updated_at"] <= self.as_of)
                and (updated_since is None or r["updated_at"] >= updated_since)]
        rows.sort(key=lambda r: (r["updated_at"], r["id"]))

        page = rows[offset: offset + limit]
        more = offset + limit < len(rows)
        return {
            "data": copy.deepcopy(page),
            "next_cursor": self._encode(offset + limit, entity, updated_since) if more else None,
        }
