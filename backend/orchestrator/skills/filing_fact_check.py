"""
Skill: filing-fact-check (finance pack, use case B4).

Takes a paragraph of prose, splits it into checkable claims about reported
financials, and verifies each one ONLY through Attested Computations — the
reconciliation template (`ac.sec_fact_reconcile`) for levels and the ratio
template (`ac.sec_ratio_by_year`) for ratios. There is no ad-hoc SQL path
in this skill at all: a claim that doesn't map onto a curated metric or
ratio gets the verdict `not_verifiable`, which is a first-class outcome
here, never a guess.

Streams the same SSE vocabulary as pipeline.run() plus two skill events:
    claim.extracted   {claims: [...]}
    claim.verdict     {id, verdict, reported, claimed, delta_pct, source}
and a terminal `answer` whose visualization kind is `verdict_table`.
Budget, byte caps and the walkthrough all come from the shared fetch path,
so a fact-check spends and reports like any other question.
"""
import asyncio
import json
import re
import time

from .. import guardrails, llm, packs, pipeline
from ...accessor import okf_loader, xbrl_metrics

RECONCILE_DOC = "ac.sec_fact_reconcile"
RATIO_DOC = "ac.sec_ratio_by_year"
TOLERANCE_PCT = 0.5     # |claimed - reported| within this → verified
MAX_CLAIMS = 8


async def _to_thread(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def _parse_number(text: str) -> float | None:
    """'$118.3 billion' → 118.3e9; '6%' → 6; '1.2bn' → 1.2e9. None when the
    claim isn't a number (a direction like 'grew')."""
    if not text:
        return None
    t = text.lower().replace(",", "")
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(trillion|tn|billion|bn|b|million|mn|m|thousand|k)?", t)
    if not m:
        return None
    value = float(m.group(1))
    scale = {"trillion": 1e12, "tn": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9,
             "million": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}.get(m.group(2) or "", 1)
    return value * scale


def _verdict(claimed: float | None, reported: float | None, is_pct: bool) -> tuple[str, float | None]:
    if reported is None:
        return "no_reported_value", None
    if claimed is None:
        return "not_verifiable", None
    if is_pct:
        # ratios are compared in percentage points, both sides as percent
        delta = abs(claimed - reported)
        return ("verified" if delta <= 0.25 else "differs"), round(delta, 3)
    if reported == 0:
        return ("verified" if claimed == 0 else "differs"), None
    delta_pct = abs(claimed - reported) / abs(reported) * 100
    return ("verified" if delta_pct <= TOLERANCE_PCT else "differs"), round(delta_pct, 3)


async def run(text: str, user_id: str, pack: str = "finance"):
    t0 = time.monotonic()
    elapsed = lambda: round(time.monotonic() - t0, 2)  # noqa: E731
    walkthrough = {"question": text, "pack": pack, "sources_considered": [], "source_used": None,
                   "queries_executed": [], "backtracks": [], "token_usage": {}, "cost": None, "elapsed_s": None}

    def finalize():
        walkthrough["elapsed_s"] = elapsed()
        return walkthrough

    try:
        yield {"event": "guardrail.started", "data": {"check": "monthly_budget"}}
        spent = await _to_thread(guardrails.check_monthly_budget, user_id)
        yield {"event": "guardrail.done", "data": {"check": "monthly_budget", "spent_usd": round(spent, 4)}}

        reconcile_doc = okf_loader.load_by_id(RECONCILE_DOC)
        ratio_doc = okf_loader.load_by_id(RATIO_DOC)
        if reconcile_doc is None or ratio_doc is None:
            yield {"event": "error", "data": {"code": "skill_unavailable", "message": "The fact-check templates aren't in this catalog.", "walkthrough": finalize()}}
            return
        walkthrough["sources_considered"] = [
            {"source_id": d.id, "title": d.title, "trust": d.trust, "score": 1.0} for d in (reconcile_doc, ratio_doc)
        ]
        yield {"event": "discover.done", "data": {"elapsed_s": elapsed(), "candidates": walkthrough["sources_considered"],
                                                   "note": "Fact-check uses only attested computations — no ad-hoc SQL."}}

        yield {"event": "plan.started", "data": {"note": "extracting claims"}}
        extracted, usage = await _to_thread(llm.extract_claims, text, xbrl_metrics.metric_keys(), xbrl_metrics.ratio_keys())
        walkthrough["token_usage"]["claims"] = usage
        claims = extracted.get("claims", [])[:MAX_CLAIMS]
        yield {"event": "plan.done", "data": {"elapsed_s": elapsed(), "shape": "fact_check", "source_id": RECONCILE_DOC,
                                               "needs_sql": False, "tokens": usage,
                                               "reasoning": f"Found {len(claims)} checkable claim(s)."}}
        yield {"event": "claim.extracted", "data": {"claims": claims}}

        rows, total_bytes = [], 0
        for claim in claims:
            metric = (claim.get("metric") or "").strip()
            entity = (claim.get("entity") or "").strip()
            fy = claim.get("fiscal_year")
            is_ratio = metric in xbrl_metrics.CURATED_RATIOS
            is_level = metric in xbrl_metrics.CURATED_METRICS
            base = {"id": claim.get("id"), "claim": claim.get("text"), "entity": entity, "metric": metric or None,
                    "fiscal_year": fy, "claimed": claim.get("claimed_value")}
            if not entity or not fy or not (is_ratio or is_level) or claim.get("claim_kind") in ("direction", "growth", "other"):
                row = {**base, "reported": None, "source": None, "accession": None, "delta_pct": None, "verdict": "not_verifiable",
                       "note": "No attested computation covers this claim as written (needs a company, a fiscal year and a curated metric)."}
                rows.append(row)
                yield {"event": "claim.verdict", "data": row}
                continue

            doc = ratio_doc if is_ratio else reconcile_doc
            candidate = {"source_id": doc.id, "kind": doc.source.get("kind", "bigquery"), "type": doc.type, "title": doc.title, "trust": doc.trust}
            params = {"company": entity, ("ratio" if is_ratio else "metric"): metric, "fiscal_year": int(fy)}
            yield {"event": "fetch.started", "data": {"source_id": doc.id, "attempt": 0, "claim_id": claim.get("id")}}
            try:
                fetched = await _to_thread(pipeline._fetch_one, candidate, {"params": params}, claim.get("text", ""))
            except guardrails.GuardrailError as exc:
                if exc.code == "monthly_budget_exceeded":
                    yield {"event": "guardrail.blocked", "data": {"code": exc.code, "message": exc.message, **exc.detail}}
                    yield {"event": "error", "data": {"code": exc.code, "message": exc.message, "walkthrough": finalize()}}
                    return
                # A byte-cap hit on one claim's query is that claim's verdict —
                # the other claims still get checked.
                yield {"event": "guardrail.blocked", "data": {"code": exc.code, "message": exc.message, "claim_id": claim.get("id"), **exc.detail}}
                row = {**base, "reported": None, "source": None, "accession": None, "delta_pct": None,
                       "verdict": "not_verifiable", "note": f"Not checked: {exc.message}"}
                rows.append(row)
                walkthrough["backtracks"].append({"from": doc.id, "reason": exc.code})
                yield {"event": "claim.verdict", "data": row}
                continue
            except Exception as exc:  # noqa: BLE001 — an unresolvable company is a verdict, not a crash
                row = {**base, "reported": None, "source": None, "accession": None, "delta_pct": None,
                       "verdict": "not_verifiable", "note": f"Couldn't fetch: {exc}"}
                rows.append(row)
                walkthrough["backtracks"].append({"from": doc.id, "reason": str(exc)})
                yield {"event": "claim.verdict", "data": row}
                continue

            total_bytes += fetched.get("bytes_billed", 0)
            for step in fetched.get("steps") or [{"source_id": doc.id, "sql": fetched.get("sql"), "params": fetched.get("params") or {},
                                                  "bytes_billed": fetched.get("bytes_billed", 0), "row_count": len(fetched["rows"])}]:
                walkthrough["queries_executed"].append({**step, "claim_id": claim.get("id")})
            yield {"event": "fetch.done", "data": {"source_id": doc.id, "rows": len(fetched["rows"]), "bytes_billed": fetched.get("bytes_billed", 0),
                                                    "sql": fetched.get("sql"), "params": fetched.get("params") or {}}}

            reported, source, accession = None, None, None
            if is_ratio:
                first = fetched["rows"][0] if fetched["rows"] else {}
                reported = first.get("ratio_pct")
                source = first.get("source")
            else:
                # prefer the API's row (it carries the filing), fall back to the bulk data set
                for r in fetched["rows"]:
                    if r.get("source") in ("sec_edgar_api", "sec_bulk_bq") and r.get("value") is not None:
                        reported, source, accession = r.get("value"), r.get("source"), r.get("accession")
                        if r.get("source") == "sec_edgar_api":
                            break
            claimed = _parse_number(str(claim.get("claimed_value") or ""))
            verdict, delta = _verdict(claimed, reported, is_ratio)
            agreement = next((r.get("agreement") for r in fetched["rows"] if r.get("source") == "reconciliation"), None)
            row = {**base, "reported": reported, "source": source, "accession": accession, "delta_pct": delta,
                   "verdict": verdict, "sources_agree": agreement,
                   "note": xbrl_metrics.CURATED_RATIOS[metric]["definition"] if is_ratio else xbrl_metrics.definition(metric)}
            rows.append(row)
            yield {"event": "claim.verdict", "data": row}

        walkthrough["source_used"] = {"id": RECONCILE_DOC, "title": reconcile_doc.title, "trust": reconcile_doc.trust}
        verified = sum(1 for r in rows if r["verdict"] == "verified")
        differs = sum(1 for r in rows if r["verdict"] == "differs")
        unverifiable = len(rows) - verified - differs
        narrative = (
            f"Checked {len(rows)} claim(s) against SEC filings through attested computations only: "
            f"{verified} verified, {differs} differ from the reported figure, {unverifiable} not verifiable. "
            "Every verified figure links to the filing it came from; anything without an attested path is left unverified rather than guessed."
        )
        cost = await _to_thread(guardrails.record_usage, user_id, total_bytes, usage, {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}, None, pack)
        walkthrough["cost"] = cost
        yield {"event": "synthesize.done", "data": {"elapsed_s": elapsed(), "query_cost_usd": cost["total_cost_usd"], "tokens": {}}}
        receipt = pipeline.build_receipt(reconcile_doc, walkthrough, total_bytes, cost)
        yield {"event": "answer", "data": {
            "question": text,
            "narrative": narrative,
            "citations": [{"source_id": reconcile_doc.id, "title": reconcile_doc.title, "trust": reconcile_doc.trust},
                          {"source_id": ratio_doc.id, "title": ratio_doc.title, "trust": ratio_doc.trust}],
            "visualization": {"kind": "verdict_table", "data": json.dumps(rows, default=str)},
            "elapsed_s": elapsed(),
            "walkthrough": finalize(),
            **({"receipt": receipt} if receipt else {}),
        }}
    except guardrails.GuardrailError as exc:
        yield {"event": "guardrail.blocked", "data": {"code": exc.code, "message": exc.message, **exc.detail}}
        yield {"event": "error", "data": {"code": exc.code, "message": exc.message, "walkthrough": finalize()}}
    except Exception as exc:  # noqa: BLE001
        yield {"event": "error", "data": {"code": "internal_error", "message": "Something went wrong checking these claims.", "walkthrough": finalize()}}
        print(f"[fact-check] unhandled error: {exc!r}")
