"""
The agent's guardrails and loop, without calling the API.

The guardrail tests read the built warehouse, so they need python run_pipeline.py --demo first.
The loop tests replace the Anthropic client with a scripted one, so they need no API key.
"""
from types import SimpleNamespace

import pytest

import config
from agent import loop
from agent.tools import MAX_ROWS, QueryRejected, Tools

pytestmark = pytest.mark.skipif(
    not config.WAREHOUSE_PATH.exists(),
    reason=f"no warehouse at {config.WAREHOUSE_PATH}; run: python run_pipeline.py --demo",
)


@pytest.fixture(scope="module")
def tools():
    return Tools("acme_apparel")


@pytest.mark.parametrize("sql", [
    "DROP TABLE acme_apparel_marts.fct_orders",
    "INSERT INTO fct_orders SELECT * FROM fct_orders",
    "CREATE TABLE x AS SELECT 1",
    "SELECT 1; DELETE FROM fct_orders",
    "COPY (SELECT 1) TO 'out.csv'",
    "ATTACH 'other.db'",
    "PRAGMA database_list",
    "SET threads = 1",
])
def test_only_a_single_select_is_allowed(tools, sql):
    with pytest.raises(QueryRejected):
        tools.check_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM bloom_skin_marts.fct_orders",
    "SELECT * FROM fct_orders WHERE order_id IN (SELECT order_id FROM bloom_skin_marts.fct_orders)",
    "SELECT * FROM raw_acme_apparel.orders",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM stg_orders",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM duckdb_tables()",
])
def test_queries_cannot_leave_the_tenant_marts(tools, sql):
    with pytest.raises(QueryRejected):
        tools.check_sql(sql)


def test_the_connection_blocks_what_the_parser_lets_through(tools):
    # getenv parses as an ordinary scalar function, so the SQL check allows it. The connection is
    # the second layer: read-only, no file or environment access, configuration locked.
    tools.check_sql("SELECT getenv('HOME')")
    with pytest.raises(Exception):
        tools.con.execute("SELECT getenv('HOME')").fetchall()
    with pytest.raises(Exception):
        tools.con.execute("SET enable_external_access = true")


def test_unqualified_tables_and_ctes_resolve_to_the_tenant(tools):
    sql = tools.check_sql("WITH w AS (SELECT * FROM fct_orders) SELECT count(*) FROM w")
    assert "acme_apparel_marts.fct_orders" in sql


def test_every_query_gets_a_row_cap(tools):
    result = tools.run_query("SELECT * FROM fct_inventory_daily")
    assert result["row_count"] == MAX_ROWS
    assert result["truncated"] is True
    assert tools.run_query("SELECT 1 AS x")["truncated"] is False


def test_data_health_never_reports_another_brands_tests():
    for brand in config.BRANDS:
        health = Tools(brand).get_data_health()
        assert health["brand"] == brand
        assert health["dbt_tests"]["status"] in {"known", "unknown"}
    # run_results.json holds one brand's build; at most one brand can see known results.
    known = [b for b in config.BRANDS if Tools(b).get_data_health()["dbt_tests"]["status"] == "known"]
    assert len(known) <= 1


# --- the loop, with a scripted client ---------------------------------------------------------

def tool_use(id_, name, **input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def text(t):
    return SimpleNamespace(type="text", text=t)


class ScriptedClient:
    """Returns canned responses in order and records every request it was sent."""
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        if not self.responses:
            return SimpleNamespace(stop_reason="tool_use", content=[tool_use("again", "list_tables")])
        stop_reason, content = self.responses.pop(0)
        return SimpleNamespace(stop_reason=stop_reason, content=content)


@pytest.fixture(autouse=True)
def tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "LOG_PATH", tmp_path / "transcript.jsonl")
    return tmp_path / "transcript.jsonl"


def test_loop_runs_tools_and_feeds_results_back_by_id(tmp_log):
    client = ScriptedClient(
        ("tool_use", [tool_use("t1", "run_query", sql="SELECT sum(spend) AS s FROM mart_marketing_daily")]),
        ("end_turn", [text("Spend was $X.")]),
    )
    result = loop.ask("spend?", "acme_apparel", client=client)

    assert result["answer"] == "Spend was $X."
    assert result["turns"] == 2
    second_request = client.requests[1]["messages"]
    tool_results = second_request[-1]["content"]
    assert tool_results[0]["tool_use_id"] == "t1"
    assert tool_results[0]["is_error"] is False
    assert "executed_sql" in tmp_log.read_text()


def test_a_rejected_query_goes_back_to_the_model_as_an_error(tmp_log):
    client = ScriptedClient(
        ("tool_use", [tool_use("t1", "run_query", sql="DELETE FROM fct_orders")]),
        ("end_turn", [text("I can only read.")]),
    )
    result = loop.ask("delete everything", "acme_apparel", client=client)

    returned = client.requests[1]["messages"][-1]["content"][0]
    assert returned["is_error"] is True
    assert "query rejected" in returned["content"]
    assert result["tool_calls"] == [{"tool": "run_query", "input": {"sql": "DELETE FROM fct_orders"}, "error": True}]


def test_parallel_tool_calls_come_back_in_one_message():
    client = ScriptedClient(
        ("tool_use", [tool_use("a", "list_tables"), tool_use("b", "get_data_health")]),
        ("end_turn", [text("done")]),
    )
    loop.ask("q", "acme_apparel", client=client)
    results = client.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


def test_the_loop_stops_at_max_turns():
    client = ScriptedClient()   # asks for a tool forever
    result = loop.ask("q", "acme_apparel", client=client)
    assert result["turns"] == loop.MAX_TURNS
    assert len(client.requests) == loop.MAX_TURNS
    assert "Stopped after" in result["answer"]
