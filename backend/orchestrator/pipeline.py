"""
The Atlas pipeline: discover -> plan -> fetch -> check -> synthesize.

This is NeuralKG's own five-stage shape, kept deliberately, with two
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

from . import discovery, guardrails, llm, packs
from ..accessor import bigquery_accessor, okf_loader, sec_edgar_accessor

MAX_BACKTRACKS = 1

# Finance pack (see packs.py / IMPLEMENTATION.md "packs"): `run()` takes a
# `pack` and threads it into discovery (which only returns that pack's
# sources), the planner/synthesis prompts (which only append that pack's
# glossary), usage accounting, and the terminal answer's `receipt`. The
# default is the public pack, so every existing caller behaves as before.


async def _to_thread(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


async def run(question: str, user_id: str, pack: str = packs.DEFAULT_PACK):
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
        "pack": pack,
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
        candidates = await _to_thread(discovery.discover, question, pack)
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
        plan, plan_usage = await _to_thread(llm.classify_and_plan, question, candidates, pack)
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
        extra_usage: dict = {}   # plan-tier calls made inside a computation (theming), priced separately
        receipt_doc = None       # the OKF doc behind the evidence, for the receipt
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
                candidate_plan, replan_usage = await _to_thread(llm.classify_and_plan, question, [candidate], pack)
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
            # Multi-step computations (composite / sample-then-theme) report
            # one queries_executed entry per step so the walkthrough shows
            # every query that actually ran, not just a roll-up.
            for step in fetched.get("steps") or [{
                "source_id": candidate["source_id"],
                "sql": fetched.get("sql"),
                "params": fetched.get("params") or {},
                "bytes_billed": bytes_billed,
                "row_count": len(rows),
            }]:
                walkthrough["queries_executed"].append(step)
                if fetched.get("steps"):
                    yield {"event": "fetch.progress", "data": {"step": step.get("step"), "source_id": step.get("source_id"), "bytes_billed": step.get("bytes_billed", 0), "rows": step.get("row_count", 0), "note": step.get("note", "")}}
            if fetched.get("usage"):
                extra_usage.update(fetched["usage"])
                walkthrough["token_usage"].update(fetched["usage"])
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
            if rows and fetched.get("verify_quotes"):
                # Narrative theming: every quoted excerpt must exist, verbatim,
                # in the sampled narrative it claims to come from. Anything
                # that doesn't is dropped here — a fabricated quote can never
                # reach the answer — and the trace says how many survived.
                rows, verified, dropped = _verify_quotes(rows, fetched["verify_quotes"])
                yield {"event": "check.done", "data": {"ok": True, "verified_quotes": verified, "dropped_quotes": dropped,
                       "note": f"Verified {verified} of {verified + dropped} quoted narratives against the sample"}}
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
            receipt_doc = fetched.get("doc")
            evidence = {
                "question": question,
                "source": walkthrough["source_used"],
                "rows": rows[:500],  # keep the synthesis prompt bounded regardless of result size
            }
            if receipt_doc is not None and getattr(receipt_doc, "citation_template", None):
                evidence["definition"] = receipt_doc.citation_template
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
        presentation, synth_usage = await _to_thread(llm.synthesize, question, evidence, pack)
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
            guardrails.record_usage, user_id, bytes_billed, total_plan_usage, synth_usage, extra_usage, pack
        )
        walkthrough["cost"] = cost
        yield {
            "event": "synthesize.done",
            "data": {"elapsed_s": elapsed(), "query_cost_usd": cost["total_cost_usd"], "tokens": synth_usage,
                     **({"generation_cost_usd": cost["generation_cost_usd"]} if "generation_cost_usd" in cost else {})},
        }

        answer = {
            "question": question,
            "narrative": presentation["narrative"],
            "citations": presentation["citations"],
            "visualization": presentation["visualization"],
            "elapsed_s": elapsed(),
            "walkthrough": finalize(),
        }
        receipt = build_receipt(receipt_doc, walkthrough, bytes_billed, cost)
        if receipt:
            answer["receipt"] = receipt
        yield {"event": "answer", "data": answer}

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
      - anything else (ported NeuralKG sources) -> generic OKF fetch

    Returns a dict of {rows, bytes_billed, sql, params, doc} — `sql`/`params`
    are what pipeline.run() puts in fetch.done and the walkthrough's
    "queries executed" list, so the actual query text is visible, not just a
    row count."""
    if candidate.get("type") == "AttestedComputation":
        doc = okf_loader.load_by_id(candidate["source_id"])
        executor = doc.executor if doc else None
        if executor == "bigquery_sample_llm":
            return _fetch_sample_then_theme(doc, plan, question)
        if executor == "composite":
            return _fetch_composite(doc, plan, question)

    if candidate["kind"] == "bigquery" and candidate.get("type") == "AttestedComputation":
        doc = okf_loader.load_by_id(candidate["source_id"])
        cap = guardrails.template_byte_cap(doc.cost_profile if doc else None)
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

    if candidate["kind"] == "sec_edgar":
        # Free, unbilled REST source — no byte cap/guardrail concept, no SQL.
        # sec_edgar_accessor.fetch_metric() returns rows=[] (not an exception)
        # when the company is real but has no reported value for this
        # metric/year, so it flows through the same `if not rows:` handling
        # as an ad-hoc BigQuery query that finds nothing. Genuine failures
        # (unresolvable company, unknown curated metric, network/HTTP errors)
        # raise SecEdgarError, which is caught by the generic `except
        # Exception` branch in run()'s fetch loop like any other fetch error.
        params = plan.get("params", {})
        doc = okf_loader.load_by_id(candidate["source_id"])
        companies = _split_companies(params.get("company", ""))
        rows, names, ciks, concepts = [], [], [], []
        for company in companies:
            result = sec_edgar_accessor.fetch_metric(
                company=company,
                metric=params.get("metric", ""),
                fiscal_year=_as_int(params.get("fiscal_year")),
            )
            names.append(result["entity_name"]); ciks.append(result["cik"]); concepts.append(result["concept"])
            for r in result["rows"]:
                rows.append({"company": result["entity_name"], **r} if len(companies) > 1 else r)
        bound_params = {"company": ", ".join(names), "cik": ", ".join(ciks), "metric": " | ".join(sorted(set(concepts)))}
        if params.get("fiscal_year"):
            bound_params["fiscal_year"] = params["fiscal_year"]
        return {"rows": rows, "bytes_billed": 0, "sql": None, "params": bound_params, "doc": doc}

    if candidate["kind"] == "sec_edgar_annual":
        # Finance pack: one annual fact, selected the 10-K way (see
        # sec_edgar_accessor.fetch_annual_fact) — the API half of
        # ac.sec_fact_reconcile, also usable on its own.
        params = plan.get("params", {})
        doc = okf_loader.load_by_id(candidate["source_id"])
        result = sec_edgar_accessor.fetch_annual_fact(
            company=params.get("company", ""), metric=params.get("metric", ""), fiscal_year=_as_int(params.get("fiscal_year")) or 0
        )
        bound_params = {"company": result["entity_name"], "cik": result["cik"], "metric": result["concept"],
                        "fiscal_year": params.get("fiscal_year"), "selection_rule": result.get("selection_rule")}
        return {"rows": result["rows"], "bytes_billed": 0, "sql": None, "params": bound_params, "doc": doc}

    if candidate["kind"] == "sec_ratio":
        params = plan.get("params", {})
        doc = okf_loader.load_by_id(candidate["source_id"])
        result = sec_edgar_accessor.compute_ratio(
            company=params.get("company", ""), ratio=params.get("ratio", ""), fiscal_year=_as_int(params.get("fiscal_year")) or 0
        )
        bound_params = {"company": result["entity_name"], "cik": result["cik"], "ratio": params.get("ratio"),
                        "fiscal_year": params.get("fiscal_year"), "definition": result.get("definition")}
        return {"rows": result["rows"], "bytes_billed": 0, "sql": None, "params": bound_params, "doc": doc}

    # Non-BigQuery source ported from NeuralKG, described purely via OKF.
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
        "narrative": "I couldn't find a data source that answers this well enough to cite. Try rephrasing, or narrow it to a specific place, time range, or metric.",
        "citations": [],
        "visualization": {"kind": "table", "data": "[]"},
    }


# --- finance pack helpers ---------------------------------------------------

def _split_companies(value) -> list[str]:
    """"Apple, Microsoft and Nvidia" -> ["Apple", "Microsoft", "Nvidia"]. A
    single name passes through untouched (including names with '&')."""
    import re as _re
    if isinstance(value, list):
        parts = [str(v) for v in value]
    else:
        parts = _re.split(r",|;|\s+and\s+|\s+vs\.?\s+|\s+versus\s+", str(value or ""))
    out = [p.strip() for p in parts if p and p.strip()]
    return out or [str(value or "")]


def _as_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _fetch_sample_then_theme(doc, plan: dict, question: str) -> dict:
    """Executor `bigquery_sample_llm` (use case A narrative theming).

    Step 1 — the template's own SQL draws a bounded sample of narratives
    through the same guarded path as every other Attested Computation (dry
    run against the template byte cap, `maximum_bytes_billed`, timeout).
    `sample_n` is clamped server-side to the template's declared maximum no
    matter what the planner extracted.

    Step 2 — the plan-tier model themes the sample using the prompt text in
    the OKF document (`computation.runtime.prompt`), never request-time
    instructions. The result rows are the themes; the raw sample is returned
    separately under `verify_quotes` so pipeline.run()'s check stage can drop
    any quote that isn't a verbatim excerpt of the narrative it cites."""
    runtime = doc.computation["runtime"]
    params = dict(plan.get("params", {}))
    max_sample = int(runtime.get("max_sample_n", 500))
    params["sample_n"] = min(_as_int(params.get("sample_n")) or max_sample, max_sample)
    for p in runtime.get("parameters", []):
        if p["name"] not in params and "default" in p:
            params[p["name"]] = p["default"]
    cap = guardrails.byte_cap_for(True, is_template=True)
    sample, bytes_billed, _doc, sql, bound = bigquery_accessor.run_attested_computation(
        doc.id, params, byte_cap=cap, timeout_seconds=guardrails.QUERY_TIMEOUT_SECONDS
    )
    steps = [{"step": "sample", "source_id": doc.id, "sql": sql, "params": bound, "bytes_billed": bytes_billed,
              "row_count": len(sample), "note": f"Sampled {len(sample)} consented narratives under the byte cap"}]
    if not sample:
        return {"rows": [], "bytes_billed": bytes_billed, "sql": sql, "params": bound, "doc": doc, "steps": steps}

    themed, usage = llm.theme_narratives(question, sample, runtime.get("prompt", ""), int(runtime.get("max_themes", 6)))
    rows = []
    for t in themed.get("themes", []):
        rows.append({
            "theme": t.get("name"),
            "share_pct": t.get("share_pct"),
            "summary": t.get("summary"),
            "quotes": t.get("quotes", []),
        })
    steps.append({"step": "theme", "source_id": doc.id, "sql": None, "params": {"model": llm.PLAN_MODEL, "narratives": len(sample)},
                  "bytes_billed": 0, "row_count": len(rows), "note": f"Themed {len(sample)} narratives into {len(rows)} themes"})
    return {"rows": rows, "bytes_billed": bytes_billed, "sql": sql, "params": bound, "doc": doc,
            "steps": steps, "usage": {"theme": usage}, "verify_quotes": sample}


def _verify_quotes(rows: list[dict], sample: list[dict]) -> tuple[list[dict], int, int]:
    """Keeps only quotes whose excerpt is a verbatim substring (whitespace-
    normalised, case-insensitive) of the narrative with that complaint_id."""
    import re as _re

    def norm(text: str) -> str:
        return _re.sub(r"\s+", " ", (text or "")).strip().lower()

    by_id = {str(r.get("complaint_id")): norm(r.get("consumer_complaint_narrative") or "") for r in sample}
    verified = dropped = 0
    out = []
    for row in rows:
        kept = []
        for q in row.get("quotes") or []:
            narrative = by_id.get(str(q.get("complaint_id")))
            excerpt = norm(q.get("excerpt", ""))
            if narrative and excerpt and excerpt in narrative:
                kept.append(q)
                verified += 1
            else:
                dropped += 1
        out.append({**row, "quotes": kept})
    return out, verified, dropped


def _fetch_composite(doc, plan: dict, question: str) -> dict:
    """Executor `composite` (use case B reconciliation). The OKF document
    lists ordered `steps`, each naming another Attested Computation and how
    to map this computation's parameters onto it; every step runs through
    its own executor with its own guardrails and is reported as its own
    queries_executed entry. `combine: reconcile` lines the step results up
    per source and adds `delta_pct` / `agreement` columns."""
    runtime = doc.computation["runtime"]
    params = plan.get("params", {})
    steps_out, rows_by_step, total_bytes = [], {}, 0
    for step in runtime.get("steps", []):
        sub_doc = okf_loader.load_by_id(step["computation"])
        if sub_doc is None:
            raise ValueError(f"Composite {doc.id} references unknown computation {step['computation']}")
        mapped = {target: params.get(source) for target, source in (step.get("params") or {}).items()}
        sub_candidate = {"source_id": sub_doc.id, "kind": sub_doc.source.get("kind", "bigquery"),
                         "type": sub_doc.type, "title": sub_doc.title, "trust": sub_doc.trust}
        result = _fetch_one(sub_candidate, {"params": mapped}, question)
        total_bytes += result.get("bytes_billed", 0)
        rows_by_step[step["name"]] = result["rows"]
        steps_out.append({"step": step["name"], "source_id": sub_doc.id, "sql": result.get("sql"), "params": result.get("params") or {},
                          "bytes_billed": result.get("bytes_billed", 0), "row_count": len(result["rows"]),
                          "note": step.get("note", "")})

    if runtime.get("combine") == "reconcile":
        rows = _reconcile(rows_by_step, runtime.get("value_field", "value"), float(runtime.get("tolerance_pct", 0.5)))
    else:
        rows = [{"step": name, **r} for name, rs in rows_by_step.items() for r in rs]
    return {"rows": rows, "bytes_billed": total_bytes, "sql": None, "params": params, "doc": doc, "steps": steps_out}


def _reconcile(rows_by_step: dict, value_field: str, tolerance_pct: float) -> list[dict]:
    """One output row per source plus a verdict row. Missing sources are
    reported as such rather than dropped, so 'the API has it but the bulk
    data set doesn't' is a visible finding."""
    values = {}
    out = []
    for name, rs in rows_by_step.items():
        first = rs[0] if rs else None
        val = first.get(value_field) if first else None
        values[name] = val
        out.append({
            "source": name,
            "value": val,
            "unit": (first or {}).get("unit"),
            "period_end": (first or {}).get("period_end"),
            "accession": (first or {}).get("accession"),
            "form": (first or {}).get("form"),
            "filed": (first or {}).get("filed"),
            "status": "reported" if val is not None else "no annual fact on file",
        })
    present = [v for v in values.values() if isinstance(v, (int, float))]
    if len(present) >= 2:
        hi, lo = max(present), min(present)
        delta_pct = (hi - lo) / abs(hi) * 100 if hi else 0.0
        agreement = "agree" if delta_pct <= tolerance_pct else "differ"
    elif len(present) == 1:
        delta_pct, agreement = None, "single source"
    else:
        delta_pct, agreement = None, "no data"
    out.append({"source": "reconciliation", "value": None, "delta_pct": round(delta_pct, 3) if delta_pct is not None else None,
                "agreement": agreement, "tolerance_pct": tolerance_pct, "status": agreement})
    return out


def build_receipt(doc, walkthrough: dict, bytes_billed: int, cost: dict | None) -> dict | None:
    """The receipt is the artefact a model-risk reviewer keeps: which
    reviewed template answered, its version and reviewer, whether it is past
    its stale_after date, every query that ran, bytes, tokens and cost. Only
    Attested Computations get one — an ad-hoc answer's walkthrough is already
    its full account, and labelling it with a reviewer would be a lie."""
    if doc is None or getattr(doc, "type", None) != "AttestedComputation":
        return None
    gov = doc.governance()
    return {
        "template_id": doc.id,
        "title": doc.title,
        **gov,
        "executor": doc.executor,
        "sources": doc.sources or [doc.source],
        "queries": [
            {"step": q.get("step"), "source_id": q.get("source_id"), "bytes_billed": q.get("bytes_billed", 0),
             "row_count": q.get("row_count", 0), "params": q.get("params") or {}}
            for q in walkthrough.get("queries_executed", [])
        ],
        "bytes_billed": bytes_billed,
        "tokens": walkthrough.get("token_usage", {}),
        "cost": cost,
        "citation_template": doc.citation_template,
    }
