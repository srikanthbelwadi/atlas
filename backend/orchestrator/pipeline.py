"""
The Atlas pipeline: discover -> plan -> fetch -> check -> synthesize.

This is Resource Raiser's own five-stage shape, kept deliberately, with two
differences: `fetch` is guarded (byte cap + timeout, see guardrails.py) and
every stage emits SSE trace events as it goes, so the frontend's live query
trace (plan §03) can render the query's progress in real time rather than
showing a spinner for up to 60 seconds.

`run()` is an async generator. Each yielded dict is one SSE event:
    {"event": "<stage>.<phase>", "data": {...json-serializable...}}
`main.py` wraps this directly in an EventSourceResponse.

Trace event vocabulary (matches the plan's §03 schema exactly):
    discover.started   / discover.done
    plan.started        / plan.done
    guardrail.started    / guardrail.done   / guardrail.blocked
    fetch.started        / fetch.progress    / fetch.done
    check.started         / check.done        / check.backtrack
    synthesize.started     / synthesize.progress / synthesize.done
    answer                                            (terminal, full payload)
    error                                             (terminal, on failure)
"""
import asyncio
import time

from . import discovery, guardrails, llm
from ..accessor import bigquery_accessor, okf_loader

MAX_BACKTRACKS = 1


async def _to_thread(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


async def run(question: str, user_id: str):
    t0 = time.monotonic()

    def elapsed():
        return round(time.monotonic() - t0, 2)

    try:
        # --- guardrail: monthly budget, checked before any spend happens ---
        yield {"event": "guardrail.started", "data": {"check": "monthly_budget"}}
        spent = await _to_thread(guardrails.check_monthly_budget, user_id)
        yield {"event": "guardrail.done", "data": {"check": "monthly_budget", "spent_usd": round(spent, 4)}}

        # --- discover: ARD candidate resolution across BQ + OKF catalog ---
        yield {"event": "discover.started", "data": {"question": question}}
        candidates = await _to_thread(discovery.discover, question)
        yield {
            "event": "discover.done",
            "data": {
                "elapsed_s": elapsed(),
                "candidates": [
                    {"source_id": c["source_id"], "title": c["title"], "trust": c["trust"], "score": round(c["score"], 3)}
                    for c in candidates
                ],
            },
        }
        if not candidates:
            yield {"event": "answer", "data": _no_evidence_answer(question)}
            return

        # --- plan: question shape + source routing (Gemini, fast tier) ---
        yield {"event": "plan.started", "data": {}}
        plan = await _to_thread(llm.classify_and_plan, question, candidates)
        chosen = next((c for c in candidates if c["source_id"] == plan.get("source_id")), candidates[0])
        yield {
            "event": "plan.done",
            "data": {"elapsed_s": elapsed(), "shape": plan.get("shape"), "source_id": chosen["source_id"], "needs_sql": plan.get("needs_sql", False)},
        }

        evidence, bytes_billed = await _fetch_with_backtrack(chosen, candidates, plan, question, user_id, elapsed)
        if evidence is None:
            yield {"event": "answer", "data": _no_evidence_answer(question)}
            return

        for ev in evidence.pop("_trace", []):
            yield ev

        # --- synthesize: grounded narrative + citations + viz (Gemini, pro tier) ---
        yield {"event": "synthesize.started", "data": {}}
        presentation = await _to_thread(llm.synthesize, question, evidence)
        yield {"event": "synthesize.progress", "data": {"stage": "composing narrative"}}

        cost = await _to_thread(guardrails.record_usage, user_id, bytes_billed)
        yield {
            "event": "synthesize.done",
            "data": {"elapsed_s": elapsed(), "query_cost_usd": round(cost, 4)},
        }

        yield {
            "event": "answer",
            "data": {
                "question": question,
                "narrative": presentation["narrative"],
                "citations": presentation["citations"],
                "visualization": presentation["visualization"],
                "elapsed_s": elapsed(),
            },
        }

    except guardrails.GuardrailError as exc:
        yield {"event": "guardrail.blocked", "data": {"code": exc.code, "message": exc.message, **exc.detail}}
        yield {"event": "error", "data": {"code": exc.code, "message": exc.message}}
    except TimeoutError as exc:
        yield {"event": "error", "data": {"code": "timeout", "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001 — last-resort trace event so the frontend never hangs on a spinner
        yield {"event": "error", "data": {"code": "internal_error", "message": "Something went wrong answering this one."}}
        print(f"[pipeline] unhandled error: {exc!r}")


async def _fetch_with_backtrack(chosen, candidates, plan, question, user_id, elapsed):
    """fetch -> check, with up to MAX_BACKTRACKS retries against the next
    candidate if the check stage rejects the evidence (e.g. empty result set,
    stale source, byte cap hit) — the plan's §03 `check.backtrack` event."""
    trace = []
    tried = set()
    remaining = [chosen] + [c for c in candidates if c["source_id"] != chosen["source_id"]]

    for attempt, candidate in enumerate(remaining[: MAX_BACKTRACKS + 1]):
        tried.add(candidate["source_id"])
        trace.append({"event": "fetch.started", "data": {"source_id": candidate["source_id"], "attempt": attempt}})

        try:
            rows, bytes_billed, doc = await _to_thread(_fetch_one, candidate, plan, question)
        except guardrails.GuardrailError as exc:
            trace.append({"event": "fetch.progress", "data": {"note": f"blocked: {exc.message}"}})
            if attempt < MAX_BACKTRACKS:
                trace.append({"event": "check.backtrack", "data": {"reason": exc.code, "from": candidate["source_id"]}})
                continue
            raise
        except TimeoutError:
            if attempt < MAX_BACKTRACKS:
                trace.append({"event": "check.backtrack", "data": {"reason": "timeout", "from": candidate["source_id"]}})
                continue
            raise

        trace.append({"event": "fetch.done", "data": {"source_id": candidate["source_id"], "rows": len(rows), "bytes_billed": bytes_billed}})

        # --- check: sanity-check the evidence before handing it to synthesis ---
        trace.append({"event": "check.started", "data": {}})
        if not rows:
            trace.append({"event": "check.done", "data": {"ok": False, "reason": "empty_result"}})
            if attempt < MAX_BACKTRACKS:
                trace.append({"event": "check.backtrack", "data": {"reason": "empty_result", "from": candidate["source_id"]}})
                continue
            return None, 0
        trace.append({"event": "check.done", "data": {"ok": True, "row_count": len(rows)}})

        evidence = {
            "question": question,
            "source": {"id": candidate["source_id"], "title": candidate["title"], "trust": candidate["trust"]},
            "rows": rows[:500],  # keep the synthesis prompt bounded regardless of result size
            "_trace": trace,
        }
        return evidence, bytes_billed

    return None, 0


def _fetch_one(candidate: dict, plan: dict, question: str):
    """Dispatches to the right accessor based on candidate kind:
      - bigquery + AttestedComputation -> guarded templated SQL (trusted path)
      - bigquery + ad-hoc               -> guarded free-form SQL (byte-capped tighter)
      - anything else (ported Resource Raiser sources) -> generic OKF fetch
    """
    if candidate["kind"] == "bigquery" and candidate.get("type") == "AttestedComputation":
        cap = guardrails.byte_cap_for(True, is_template=True)
        params = plan.get("params", {})
        rows, bytes_billed, doc = bigquery_accessor.run_attested_computation(
            candidate["source_id"], params, byte_cap=cap, timeout_seconds=guardrails.QUERY_TIMEOUT_SECONDS
        )
        return rows, bytes_billed, doc

    if candidate["kind"] == "bigquery":
        cap = guardrails.byte_cap_for(True, is_template=False)
        sql = plan.get("sql")
        if not sql:
            raise ValueError(f"Planner marked needs_sql but produced no SQL for {candidate['source_id']}")
        rows, bytes_billed = bigquery_accessor.run(sql, byte_cap=cap, timeout_seconds=guardrails.QUERY_TIMEOUT_SECONDS)
        return rows, bytes_billed, None

    # Non-BigQuery source ported from Resource Raiser, described purely via OKF.
    doc = okf_loader.load_by_id(candidate["source_id"])
    return [{"note": "generic OKF fetch not yet wired", "doc_id": candidate["source_id"]}], 0, doc


def _no_evidence_answer(question: str) -> dict:
    return {
        "question": question,
        "narrative": "I couldn't find a public dataset that answers this well enough to cite. Try rephrasing, or narrow it to a specific place, time range, or metric.",
        "citations": [],
        "visualization": {"kind": "table", "data": "[]"},
    }
