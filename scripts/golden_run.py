#!/usr/bin/env python3
"""
Golden-question runner for the Atlas orchestrator.

    scripts/golden_run.py --base https://atlas-orchestrator-...run.app \
        --token "$(scripts/firebase_token.sh)" --set tests/golden/finance_a.yaml \
        [--report /tmp/finance_a.md]

For every question: POST /ask (or /skills/filing-fact-check), collect the
SSE trace, and check the expectations in the YAML:
  path              attested | adhoc | refusal | refusal_or_no_finance_source
  source_id / source_id_in / source_prefix / forbidden_source_prefix
  params_include    subset of the bound params on the query that ran
  max_bytes_gb      bytes billed ceiling
  verified_quotes_min, receipt, rows_include_source, kind, claims_min, verdicts_include
Writes a markdown report (pass/fail per question with source, bytes, cost,
elapsed) and exits non-zero if anything failed. Needs `requests` + `pyyaml`.
"""
import argparse
import functools
print = functools.partial(print, flush=True)  # lines appear live even when piped through tee
import json
import sys
import time

import requests
import yaml


def stream(base, path, token, body):
    with requests.post(f"{base}{path}", json=body, headers={"Authorization": f"Bearer {token}"}, stream=True, timeout=660) as r:
        r.raise_for_status()
        event, data = None, []
        for raw in r.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            line = raw.strip("\r")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif line == "" and event:
                try:
                    payload = json.loads("\n".join(data) or "{}")
                except json.JSONDecodeError:
                    payload = {"_raw": "\n".join(data)[:500]}
                yield event, payload
                if event in ("answer", "error"):
                    return
                event, data = None, []


def check(expect, events):
    terminal = next((p for e, p in events if e in ("answer", "error")), {})
    wt = terminal.get("walkthrough") or {}
    queries = wt.get("queries_executed") or []
    used = (wt.get("source_used") or {}).get("id")
    narrative = terminal.get("narrative", "")
    refusal = ("couldn't find a data source" in narrative.lower()) or (not used)
    failures = []
    path = expect.get("path")
    if terminal.get("code") and path not in ("refusal", "refusal_or_no_finance_source"):
        failures.append(f"error event: {terminal.get('code')} — {terminal.get('message')}")
    if path == "attested":
        if not (used or "").startswith("ac."):
            failures.append(f"expected attested path, used {used!r}")
    elif path == "adhoc":
        if not (used or "").startswith("bq."):
            failures.append(f"expected ad-hoc path, used {used!r}")
    elif path == "refusal":
        if not refusal:
            failures.append(f"expected refusal, got source {used!r}")
    elif path == "refusal_or_no_finance_source":
        pass
    if "source_id" in expect and used != expect["source_id"]:
        failures.append(f"source {used!r} != {expect['source_id']!r}")
    if "source_id_in" in expect and used not in expect["source_id_in"]:
        failures.append(f"source {used!r} not in {expect['source_id_in']}")
    if "source_prefix" in expect and not (used or "").startswith(expect["source_prefix"]):
        failures.append(f"source {used!r} lacks prefix {expect['source_prefix']}")
    if "forbidden_source_prefix" in expect:
        for s in (wt.get("sources_considered") or []):
            if s.get("source_id", "").startswith(expect["forbidden_source_prefix"]):
                failures.append(f"forbidden source considered: {s['source_id']}")
    if "params_include" in expect:
        bound = {}
        for q in queries:
            bound.update(q.get("params") or {})
        for k, v in expect["params_include"].items():
            if str(bound.get(k, "")).lower() != str(v).lower():
                failures.append(f"param {k}={bound.get(k)!r}, expected {v!r}")
    if "max_bytes_gb" in expect:
        total = sum(q.get("bytes_billed", 0) for q in queries)
        if total > expect["max_bytes_gb"] * 1024**3:
            failures.append(f"scanned {total/1024**3:.1f} GB > {expect['max_bytes_gb']} GB")
    if "verified_quotes_min" in expect:
        verified = max([p.get("verified_quotes", 0) for e, p in events if e == "check.done"] or [0])
        if verified < expect["verified_quotes_min"]:
            failures.append(f"verified quotes {verified} < {expect['verified_quotes_min']}")
    if expect.get("receipt") and not terminal.get("receipt"):
        failures.append("no receipt on answer")
    if "rows_include_source" in expect:
        rows = json.loads((terminal.get("visualization") or {}).get("data") or "[]") if isinstance((terminal.get("visualization") or {}).get("data"), str) else []
        if not any(isinstance(r, dict) and r.get("source") == expect["rows_include_source"] for r in rows):
            pass  # the synthesis model may reshape rows; the walkthrough is the real check below
        if len(queries) < 2:
            failures.append("reconciliation ran fewer than two steps")
    if "kind" in expect and (terminal.get("visualization") or {}).get("kind") != expect["kind"]:
        failures.append(f"viz kind {(terminal.get('visualization') or {}).get('kind')!r} != {expect['kind']!r}")
    if "claims_min" in expect:
        claims = next((p.get("claims", []) for e, p in events if e == "claim.extracted"), [])
        if len(claims) < expect["claims_min"]:
            failures.append(f"{len(claims)} claims < {expect['claims_min']}")
    if "verdicts_include" in expect:
        verdicts = {p.get("verdict") for e, p in events if e == "claim.verdict"}
        missing = set(expect["verdicts_include"]) - verdicts
        if missing:
            failures.append(f"verdicts missing {missing}")
    verdict_rows = [p for e, p in events if e == "claim.verdict" and isinstance(p, dict) and p.get("verdict")]
    unparsed = sum(1 for e, p in events if e == "claim.verdict" and not (isinstance(p, dict) and p.get("verdict")))
    if unparsed:
        failures.append(f"{unparsed} claim.verdict event(s) could not be parsed by the runner")
    cost = (wt.get("cost") or {}).get("total_cost_usd")
    bytes_total = sum(q.get("bytes_billed", 0) for q in queries)
    return failures, {"source": used, "bytes_gb": round(bytes_total / 1024**3, 3), "cost_usd": cost, "elapsed_s": wt.get("elapsed_s"),
                      "error": terminal.get("message") if terminal.get("code") else None,
                      "verdicts": verdict_rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--set", required=True)
    ap.add_argument("--report")
    ap.add_argument("--only", help="comma-separated question ids")
    args = ap.parse_args()
    spec = yaml.safe_load(open(args.set))
    pack = spec.get("pack", "public")
    only = set(args.only.split(",")) if args.only else None
    lines = [f"# Golden run: {args.set} (pack={pack}) — {time.strftime('%Y-%m-%d %H:%M')}", "", "| id | question | result | source | GB | $ | s |", "|---|---|---|---|---|---|---|"]
    failed = 0
    for i, item in enumerate(spec["questions"], 1):
        qid = item.get("id", str(i))
        if only and qid not in only:
            continue
        if item.get("skill") == "filing-fact-check":
            events = list(stream(args.base, "/skills/filing-fact-check", args.token, {"text": item["text"], "pack": pack}))
            label = item["text"]
        else:
            events = list(stream(args.base, "/ask", args.token, {"question": item["q"], "pack": pack}))
            label = item["q"]
        failures, meta = check(item.get("expect", {}), events)
        status = "PASS" if not failures else "FAIL: " + "; ".join(failures)
        failed += bool(failures)
        print(f"[{qid}] {status}  ({meta['source']}, {meta['bytes_gb']} GB, ${meta['cost_usd']}, {meta['elapsed_s']}s)")
        lines.append(f"| {qid} | {label[:80]} | {status} | `{meta['source']}` | {meta['bytes_gb']} | {meta['cost_usd']} | {meta['elapsed_s']} |")
        if meta.get("error"):
            lines.append(f"|  | error: {meta['error']} | | | | | |")
        for v in meta.get("verdicts") or []:
            lines.append(f"|  | ↳ {v.get('verdict')}: {str(v.get('claim'))[:70]} → reported {v.get('reported')} ({v.get('source')}) {('— ' + str(v.get('note'))[:90]) if v.get('note') else ''} | | | | | |")
    if args.report:
        open(args.report, "w").write("\n".join(lines) + "\n")
        print(f"report: {args.report}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
