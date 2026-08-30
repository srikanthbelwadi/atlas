"""
The Atlas pipeline: discover -> plan -> fetch -> check -> synthesize.

This is Resource Raiser's own five-stage shape, kept deliberately, with two
differences: `fetch` is guarded (byte cap + timeout, see guardrails.py) and
every stage emits SSE trace events as it goes, so the frontend's live query
trace (plan §03) can render the query's progress in real time rather than
showing a spinner for up to the full ~10-minute query budget.

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

IMPORTANT: the fetch/check loop used to live in a separate helper
(`_fetch_with_backtrack`) that built up a local list of trace events and only
returned them — all at once — after a successful fetch+check. That had two
real bugs, both found by actually running a query end to end rather than by
reading the code:

  1. Every fetch/check event for the whole attempt was withheld from the
     client until the loop finished, so the "live" trace wasn't live at all
     for that phase — it arrived in one batch right before synthesis, not
     incrementally as each step happened.
  2. Worse: if `_fetch_one` raised anything other than GuardrailError or
     TimeoutError (e.g. a planner-picked AttestedComputation template
     missing a required parameter — see llm.py's docstring for that bug),
     the exception propagated out of the helper *before it ever returned*,
     so the whole accumulated trace for that attempt was silently lost. The
     client got nothing but a generic "Something went wrong" — no
     fetch.started, no indication of which source was tried or why it
     failed.

The loop is inlined into `run()` below specifically so every event yields
immediately, and so a per-candidate exception (of any kind, not just the two
specific ones the retry logic originally anticipated) can still backtrack to
the next candidate — or fail with a specific, real reason — without losing
any of the trace already emitted.

A THIRD real bug in this same loop, found later (asking about India's GDP
per capita): `classify_and_plan` was called exactly once, before the loop,
against `chosen` — but its returned `plan` (including the one `sql` string
Gemini drafted) was then reused verbatim for every backtrack attempt, even
though each attempt targets a DIFFERENT candidate with a different real
schema. SQL drafted for candidate A's columns doesn't fit candidate B's
table, so backtracking just traded one failure for another, less
informative one ("Planner marked needs_sql but produced no SQL"). Fixed by
redrafting a fresh, single-candidate plan for every attempt after the
first — see the `attempt == 0` check in the loop below.
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

    # Accumulated across the whole run and attached to the terminal event
    # (answer OR error) as "walkthrough" — sources considered, the actual
    # query text and bound params for everything that was executed, every
    # backtrack and why, and real Gemini token cost. This is what a user
    # asking "what did Atlas actually do" reads after the fact, on success
    # or failure alike.
    walkthrough = {
        "question": question,
        "sources_considered": [],
        "source_used": None,
        "queries_executed": [],
        "backtracks": [],
        "token_usage": {},
        "cost": None,
        "elapsed_s": None,
    }

    def finalize():
        walkthrough["elapsed_s"] = elapsed()
        return walkthrough

    try:
        # --- guardrail: monthly budget, checked before any spend happens ---
        yield {"event": "guardrail.started", "data": {"check": "monthly_budget"}}
        spent = await _to_thread(guardrails.check_monthly_budget, user_id)
        yield {"event": "guardrail.done", "data": {"check": "monthly_budget", "spent_usd": round(spent, 4)}}

        # --- discover: ARD candidate resolution across BQ + OKF catalog ---
        yield {"event": "discover.started", "data": {"question": question}}
        candidates = await _to_thread(discovery.discover, question)
        walkthrough["sources_considered"] = [
            {"source_id": c["source_id"], "title": c["title"], "trust": c["trust"], "score": round(c["score"], 3)}
            for c in candidates
        ]
        yield {"event": "discover.done", "data": {"elapsed_s": elapsed(), "candidates": walkthrough["sources_considered"]}}
        if not candidates:
            yield {"event": "answer", "data": {**_no_evidence_answer(question), "walkthrough": finalize()}}
            return

        # --- plan: question shape + source routing (Gemini, fast tier) ---
        yield {"event": "plan.started", "data": {}}
        plan, plan_usage = await _to_thread(llm.classify_and_plan, question, candidates)
        walkthrough["token_usage"]["plan"] = plan_usage
        chosen = next((c for c in candidates if c["source_id"] == plan.get("source_id")), candidates[0])
        yield {
            "event": "plan.done",
            "data": {
                "elapsed_s": elapsed(),
                "shape": plan.get("shape"),
                "source_id": chosen["source_id"],
                "needs_sql": plan.get("needs_sql", False),
                "tokens": plan_usage,
                "reasoning": plan.get("reasoning", ""),
            },
        }

        # --- fetch -> check, with up to MAX_BACKTRACKS retries against the
        # next candidate if a fetch fails outright or the check stage rejects
        # the evidence (empty result, byte cap, timeout). Inlined here (see
        # module docstring) so every event streams live and survives a
        # failed attempt instead of being lost with it. ---
        evidence = None
        bytes_billed = 0
        remaining = [chosen] + [c for c in candidates if c["source_id"] != chosen["source_id"]]

        for attempt, candidate in enumerate(remaining[: MAX_BACKTRACKS + 1]):
            # `plan` was drafted once, up front, against `chosen` (attempt 0)
            # specifically — its `sql`/`params` are only valid for that one
            # candidate's real schema. Reusing it verbatim on a backtrack
            # attempt against a DIFFERENT candidate was a real architectural
            # bug found live: asked about India's GDP per capita, attempt 1
            # backtracked to a different World Bank table and failed with
            # "Planner marked needs_sql but produced no SQL" — the SQL in
            # `plan` was Gemini's answer for the FIRST candidate's columns,
            # not this one's, so it was either absent or wrong for the table
            # actually being queried. Fix: redraft a fresh plan scoped to
            # just this one candidate before fetching from it, for every
            # attempt after the first — costs one extra fast-tier Gemini
            # call, only on a backtrack, which is already the slow/failing
            # path.
            if attempt == 0:
                candidate_plan = plan
            else:
                yield {"event": "plan.started", "data": {"note": f"redrafting for {candidate['source_id']}"}}
                candidate_plan, replan_usage = await _to_thread(llm.classify_and_plan, question, [candidate])
                walkthrough["token_usage"][f"plan_backtrack_{attempt}"] = replan_usage
                yield {
                    "event": "plan.done",
                    "data": {
                        "elapsed_s": elapsed(),
                        "shape": candidate_plan.get("shape"),
                        "source_id": candidate["source_id"],
                        "needs_sql": candidate_plan.get("needs_sql", False),
                        "tokens": replan_usage,
                        "reasoning": candidate_plan.get("reasoning", ""),
                        "note": "redrafted for this backtrack candidate",
                    },
                }

            yield {"event": "fetch.started", "data": {"source_id": candidate["source_id"], "attempt": attempt}}
            can_retry = attempt < MAX_BACKTRACKS

            try:
                fetched = await _to_thread(_fetch_one, candidate, candidate_plan, question)
            except guardrails.GuardrailError as exc:
                yield {"event": "fetch.progress", "data": {"note": f"blocked: {exc.message}"}}
                walkthrough["backtracks"].append({"from": candidate["source_id"], "reason": exc.code})
                if can_retry:
                    yield {"event": "check.backtrack", "data": {"reason": exc.code, "from": candidate["source_id"]}}
                    continue
                yield {"event": "guardrail.blocked", "data": {"code": exc.code, "message": exc.message, **exc.detail}}
                yield {"event": "error", "data": {"code": exc.code, "message": exc.message, "walkthrough": finalize()}}
                return
            except TimeoutError as exc:
                yield {"event": "fetch.progress", "data": {"note": f"timed out: {exc}"}}
                walkthrough["backtracks"].append({"from": candidate["source_id"], "reason": "timeout"})
                if can_retry:
                    yield {"event": "check.backtrack", "data": {"reason": "timeout", "from": candidate["source_id"]}}
                    continue
                yield {"event": "error", "data": {"code": "timeout", "message": str(exc), "walkthrough": finalize()}}
                return
            except Exception as exc:  # noqa: BLE001 — e.g. the planner chose an
                # AttestedComputation template but didn't extract a required
                # parameter, or drafted SQL that BigQuery rejects. Try the next
                # candidate instead of failing the whole question outright —
                # this is the fix for the exact failure mode that motivated
                # this rewrite (see module + llm.py docstrings).
                yield {"event": "fetch.progress", "data": {"note": f"couldn't fetch from {candidate['source_id']}: {exc}"}}
                walkthrough["backtracks"].append({"from": candidate["source_id"], "reason": str(exc)})
                if can_retry:
                    yield {"event": "check.backtrack", "data": {"reason": "fetch_error", "from": candidate["source_id"]}}
                    continue
                yield {
                    "event": "error",
                    "data": {"code": "fetch_failed", "message": "Couldn't fetch data for this question.", "walkthrough": finalize()},
                }
                print(f"[pipeline] fetch failed for every candidate tried, last error: {exc!r}")
                return

            rows = fetched["rows"]
            bytes_billed = fetched["bytes_billed"]
            walkthrough["queries_executed"].append({
                "source_id": candidate["source_id"],
                "sql": fetched.get("sql"),
                "params": fetched.get("params") or {},
                "bytes_billed": bytes_billed,
                "row_count": len(rows),
            })
            yield {
                "event": "fetch.done",
                "data": {
                    "source_id": candidate["source_id"],
                    "rows": len(rows),
                    "bytes_billed": bytes_billed,
                    "sql": fetched.get("sql"),
                    "params": fetched.get("params") or {},
                },
            }

            # --- check: sanity-check the evidence before handing it to synthesis ---
            yield {"event": "check.started", "data": {}}
            if not rows:
                yield {"event": "check.done", "data": {"ok": False, "reason": "empty_result"}}
                walkthrough["backtracks"].append({"from": candidate["source_id"], "reason": "empty_result"})
                if can_retry:
                    yield {"event": "check.backtrack", "data": {"reason": "empty_result", "from": candidate["source_id"]}}
                    continue
                yield {"event": "answer", "data": {**_no_evidence_answer(question), "walkthrough": finalize()}}
                return

            preview = rows[:3]
            yield {"event": "check.done", "data": {"ok": True, "row_count": len(rows), "preview": preview}}
            walkthrough["source_used"] = {"id": candidate["source_id"], "title": candidate["title"], "trust": candidate["trust"]}
            evidence = {
                "question": question,
                "source": walkthrough["source_used"],
                "rows": rows[:500],  # keep the synthesis prompt bounded regardless of result size
            }
            break

        if evidence is None:
            # Every candidate was tried and none produced usable rows —
            # unreachable in practice given the explicit `return`s above on
            # the final attempt of every failure branch, but kept as a
            # defensive fallback rather than let `evidence` reach the
            # synthesize step as None.
            yield {"event": "answer", "data": {**_no_evidence_answer(question), "walkthrough": finalize()}}
            return

        # --- synthesize: grounded narrative + citations + viz (Gemini, pro tier) ---
        # `evidence` is already fully known here (rows fetched, which source,
        # its trust level), so synthesize.started can say something real
        # instead of an empty "started" marker — this is the actual reasoning
        # trace for this stage, not a made-up progress bar, since a single
        # synchronous model call has no real intermediate progress to report.
        yield {
            "event": "synthesize.started",
            "data": {
                "note": (
                    f"Drafting a grounded narrative from {len(evidence['rows'])} row"
                    f"{'s' if len(evidence['rows']) != 1 else ''} in {evidence['source']['title']}, "
                    f"to be cited as {evidence['source']['trust']}."
                )
            },
        }
        presentation, synth_usage = await _to_thread(llm.synthesize, question, evidence)
        walkthrough["token_usage"]["synthesize"] = synth_usage
        yield {
            "event": "synthesize.progress",
            "data": {
                "stage": "composing narrative",
                "note": f"Chose a {presentation.get('visualization', {}).get('kind', 'table')} visualization, {len(presentation.get('citations', []))} citation(s).",
            },
        }

        # A backtrack redraft (see the loop above) is a real extra Gemini
        # call with its own real cost, recorded under its own
        # "plan_backtrack_N" key in token_usage as it happens. Sum all of
        # those together with the original "plan" entry here so the combined
        # total — not just the original single-candidate call — is what
        # actually gets billed against the monthly budget below.
        total_plan_usage = {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for key, usage in walkthrough["token_usage"].items():
            if key == "plan" or key.startswith("plan_backtrack_"):
                for field in total_plan_usage:
                    total_plan_usage[field] += usage.get(field, 0)
        # Overwrite "plan" with the combined total (rather than adding a new
        # key) so the frontend's existing tokenUsage.plan display — which
        # only ever reads that one key — shows the real total without
        # needing its own change to know about backtrack redraft calls.
        walkthrough["token_usage"]["plan"] = total_plan_usage

        cost = await _to_thread(
            guardrails.record_usage, user_id, bytes_billed, total_plan_usage, synth_usage
        )
        walkthrough["cost"] = cost
        yield {
            "event": "synthesize.done",
            "data": {"elapsed_s": elapsed(), "query_cost_usd": cost["total_cost_usd"], "tokens": synth_usage},
        }

        yield {
            "event": "answer",
            "data": {
                "question": question,
                "narrative": presentation["narrative"],
                "citations": presentation["citations"],
                "visualization": presentation["visualization"],
                "elapsed_s": elapsed(),
                "walkthrough": finalize(),
            },
        }

    except guardrails.GuardrailError as exc:
        yield {"event": "guardrail.blocked", "data": {"code": exc.code, "message": exc.message, **exc.detail}}
        yield {"event": "error", "data": {"code": exc.code, "message": exc.message, "walkthrough": finalize()}}
    except TimeoutError as exc:
        yield {"event": "error", "data": {"code": "timeout", "message": str(exc), "walkthrough": finalize()}}
    except Exception as exc:  # noqa: BLE001 — last-resort trace event so the frontend never hangs on a spinner
        yield {
            "event": "error",
            "data": {"code": "internal_error", "message": "Something went wrong answering this one.", "walkthrough": finalize()},
        }
        print(f"[pipeline] unhandled error: {exc!r}")


def _fetch_one(candidate: dict, plan: dict, question: str) -> dict:
    """Dispatches to the right accessor based on candidate kind:
      - bigquery + AttestedComputation -> guarded templated SQL (trusted path)
      - bigquery + ad-hoc               -> guarded free-form SQL (byte-capped tighter)
      - anything else (ported Resource Raiser sources) -> generic OKF fetch

    Returns a dict of {rows, bytes_billed, sql, params, doc} — `sql`/`params`
    are what pipeline.run() puts in fetch.done and the walkthrough's
    "queries executed" list, so the actual query text is visible, not just a
    row count."""
    if candidate["kind"] == "bigquery" and candidate.get("type") == "AttestedComputation":
        cap = guardrails.byte_cap_for(True, is_template=True)
        params = plan.get("params", {})
        rows, bytes_billed, doc, sql, bound_params = bigquery_accessor.run_attested_computation(
            candidate["source_id"], params, byte_cap=cap, timeout_seconds=guardrails.QUERY_TIMEOUT_SECONDS
        )
        return {"rows": rows, "bytes_billed": bytes_billed, "sql": sql, "params": bound_params, "doc": doc}

    if candidate["kind"] == "bigquery":
        cap = guardrails.byte_cap_for(True, is_template=False)
        sql = plan.get("sql")
        if not sql:
            raise ValueError(f"Planner marked needs_sql but produced no SQL for {candidate['source_id']}")
        rows, bytes_billed = bigquery_accessor.run(sql, byte_cap=cap, timeout_seconds=guardrails.QUERY_TIMEOUT_SECONDS)
        return {"rows": rows, "bytes_billed": bytes_billed, "sql": sql, "params": {}, "doc": None}

    # Non-BigQuery source ported from Resource Raiser, described purely via OKF.
    doc = okf_loader.load_by_id(candidate["source_id"])
    return {
        "rows": [{"note": "generic OKF fetch not yet wired", "doc_id": candidate["source_id"]}],
        "bytes_billed": 0,
        "sql": None,
        "params": {},
        "doc": doc,
    }


def _no_evidence_answer(question: str) -> dict:
    return {
        "question": question,
        "narrative": "I couldn't find a public dataset that answers this well enough to cite. Try rephrasing, or narrow it to a specific place, time range, or metric.",
        "citations": [],
        "visualization": {"kind": "table", "data": "[]"},
    }
