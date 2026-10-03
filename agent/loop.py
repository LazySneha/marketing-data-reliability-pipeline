"""
The agent loop: the model picks a tool, we run it, the model reads the result and picks again,
until it answers in plain text or runs out of turns.
"""
import json
import time
import uuid
from pathlib import Path

import anthropic

from agent.tools import QueryRejected, Tools, TOOL_DEFINITIONS

MODEL = "claude-opus-5-5"
MAX_TURNS = 10          # model calls per question; a loop that hasn't answered by then won't
LOG_PATH = Path(__file__).resolve().parent / "logs" / "transcript.jsonl"

SYSTEM_PROMPT = """\
You answer business questions about one e-commerce brand, {brand}, using its dbt marts in DuckDB.
You can only see this brand. If asked about another brand, say you are scoped to {brand} and
answer nothing about the other one.

Rules:
- Never state a number you did not get from a run_query result in this conversation. If a query
  returns no rows or NULL, say there is no data for that; do not estimate.
- Every number you give must say which brand and which date range it covers.
- The data can stop before today. Call get_data_health to find the latest date, and resolve
  relative dates against it, not the calendar: "last week" is the last complete Monday-Sunday
  week on or before the latest report_date; "last month" is the last complete calendar month.
  Say what you anchored to.
- End with a one-line data note: the latest date the answer is based on, and any failing or
  warning dbt tests on the models you used. If test status is unknown, say so.

For budget or "what should we do" questions, ground the recommendation in queried numbers
(recent spend, MER, spend at risk) and say it is a recommendation, not a forecast.
Keep answers short: lead with the answer, then the date range, then the data note.\
"""

# Business definitions, kept separate so the evals can measure what they are worth (--no-definitions).
DEFINITIONS = """

Definitions (the marts already implement these; use them, don't re-derive):
- Revenue means net revenue (gross minus refunds, refunds dated to the order) unless the user
  says gross. Platform-reported revenue is never revenue.
- MER = sum(net_revenue) / sum(spend). ROAS = sum(attributed_net_revenue) / sum(spend).
  For any ratio over a period, divide the sums; never average the daily ratios.
- Revenue lost to stockouts is the line revenue of out-of-stock cancellations in fct_order_items.
  mart_spend_at_risk.lost_revenue_out_of_stock only covers days a campaign was spending on an
  at-risk SKU, so it undercounts the total.\
"""


def log(event: dict) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}, default=str) + "\n")


def run_tool(funcs: dict, block) -> tuple[dict, bool]:
    """Run one tool call. Errors are returned to the model, not raised: it can read them and retry."""
    try:
        return funcs[block.name](**block.input), False
    except QueryRejected as e:
        return {"error": f"query rejected: {e}"}, True
    except Exception as e:  # a bad column name, a type error in SQL, ...
        return {"error": f"{type(e).__name__}: {e}"}, True


def ask(question: str, brand: str, client=None, verbose: bool = False, definitions: bool = True) -> dict:
    client = client or anthropic.Anthropic()
    tools = Tools(brand)
    funcs = tools.functions()
    session = uuid.uuid4().hex[:8]
    calls = []
    log({"session": session, "brand": brand, "event": "question", "question": question})

    # The conversation is just this list. The API is stateless: every turn we resend all of it.
    messages = [{"role": "user", "content": question}]

    for turn in range(1, MAX_TURNS + 1):
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT.format(brand=brand) + (DEFINITIONS if definitions else ""),
            tools=TOOL_DEFINITIONS,
            messages=messages,
            output_config={"effort": "medium"},
            cache_control={"type": "ephemeral"},    # turn N+1 resends turn N's prefix; cache it
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                     # if this model declines, retry on another
        )
        # Append the whole response, not just its text: it holds the tool_use blocks (whose ids the
        # tool_results must reference) and any thinking blocks the model needs to keep its reasoning.
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            answer = "".join(b.text for b in resp.content if b.type == "text")
            if resp.stop_reason == "refusal":
                answer = answer or "The model declined to answer this question."
            elif resp.stop_reason == "max_tokens":
                answer += "\n[answer cut off at max_tokens]"
            log({"session": session, "event": "answer", "turns": turn,
                 "stop_reason": resp.stop_reason, "answer": answer})
            return {"answer": answer, "turns": turn, "tool_calls": calls}

        # The model may ask for several tools in one turn. Run them all and return every result in
        # ONE user message, each tagged with the tool_use id it answers.
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            out, is_error = run_tool(funcs, block)
            calls.append({"tool": block.name, "input": block.input, "error": is_error})
            log({"session": session, "event": "tool_call", "turn": turn, "tool": block.name,
                 "input": block.input, "is_error": is_error,
                 **({"executed_sql": out.get("executed_sql"), "row_count": out.get("row_count"),
                     "truncated": out.get("truncated")} if block.name == "run_query" else {}),
                 **({"error": out["error"]} if is_error else {})})
            if verbose:
                detail = block.input.get("sql", "") if block.name == "run_query" else ""
                print(f"  [turn {turn}] {block.name} {detail}{'  -> ERROR ' + out['error'] if is_error else ''}")
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": json.dumps(out, default=str), "is_error": is_error})
        messages.append({"role": "user", "content": results})

    log({"session": session, "event": "gave_up", "turns": MAX_TURNS})
    return {"answer": f"Stopped after {MAX_TURNS} turns without an answer.", "turns": MAX_TURNS,
            "tool_calls": calls}
