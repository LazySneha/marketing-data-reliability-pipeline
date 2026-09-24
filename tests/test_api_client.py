import pytest

from conftest import record
from ingestion.ingest import fetch_page_with_retry, paginate
from source.fake_api import BadRequestError, RateLimitError, ServerError


class ScriptedAPI:
    """Returns (or raises) the next scripted response on every call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def get_page(self, entity, cursor=None, updated_since=None):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_paginate_follows_cursor_until_last_page(make_api):
    orders = [record(f"o{i:03d}", f"2026-07-01T00:00:{i % 60:02d}Z") for i in range(120)]
    api = make_api(orders=orders)

    ids = [r["id"] for r in paginate(api, "orders")]

    assert sorted(ids) == sorted(o["id"] for o in orders)
    assert api.calls == 3  # 50 + 50 + 20


def test_paginate_with_no_results_makes_one_call(make_api):
    api = make_api(orders=[record("o1", "2026-07-01T00:00:00Z")])

    assert list(paginate(api, "orders", updated_since="2027-01-01T00:00:00Z")) == []
    assert api.calls == 1


def test_retries_rate_limit_and_server_errors_then_succeeds():
    page = {"data": [], "next_cursor": None}
    api = ScriptedAPI(RateLimitError(retry_after=2.0), ServerError("503"), page)
    sleeps = []

    result = fetch_page_with_retry(api, "orders", None, None, base_delay=0.1, sleep=sleeps.append)

    assert result == page
    assert api.calls == 3
    assert sleeps[0] == 2.0                 # honours Retry-After
    assert 0.2 <= sleeps[1] <= 0.3          # attempt 2: base * 2, plus up to base of jitter


def test_non_retryable_error_fails_immediately():
    api = ScriptedAPI(BadRequestError("400"))
    sleeps = []

    with pytest.raises(BadRequestError):
        fetch_page_with_retry(api, "orders", None, None, sleep=sleeps.append)

    assert api.calls == 1
    assert sleeps == []


def test_gives_up_after_max_attempts():
    api = ScriptedAPI(*[ServerError("503")] * 3)
    sleeps = []

    with pytest.raises(ServerError):
        fetch_page_with_retry(api, "orders", None, None, max_attempts=3, sleep=sleeps.append)

    assert api.calls == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]            # backoff grows
