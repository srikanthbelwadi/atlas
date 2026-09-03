---
name: peer-benchmark
description: Compare a bank with a size-defined peer set on stated ratios (ROA, ROE, equity-to-assets) through Atlas's finance pack, choosing and naming the definition explicitly — FDIC regulatory ratios versus XBRL 10-K ratios — so the two are never silently mixed.
---

# Peer benchmark

## When to use
"How does `<bank>` compare with the largest banks on ROA/ROE?", "peer table
of the biggest banks by deposits", "is `<bank>`'s efficiency ratio better
than peers?".

## Procedure
1. **Resolve the entity.** `POST /ask` "Which bank is `<name>` — what are
   its FDIC certificate and SEC CIK?" → `ac.entity_resolve`. More than one
   row back means ambiguous: ask the user which, do not pick.
2. **Choose the definition and say so.** If the question says "FDIC",
   "regulatory", "call report", or names no source for *banks*, use the
   FDIC definition; if it says "10-K", "filings", "XBRL", or the entity is
   not a bank, use the XBRL definition. Write the choice into the output's
   first line.
3. **Peer table.** "Compare return on assets for the `<N>` largest US banks
   by `<deposits|assets>`, using the latest FDIC figures." →
   `ac.fdic_peer_ratios` (columns `roa_pct_fdic`, `roe_pct_fdic`,
   `equity_to_assets_pct`, sizes in $bn).
4. **Target bank, same definition.** FDIC: it is already a row of the peer
   table when it is a top-N bank; otherwise ask "FDIC-reported ROA and ROE
   for `<bank>`" (ad-hoc, machine-confirmed — label it). XBRL: "`<bank>`'s
   return on assets in fiscal `<year>` from its filings" →
   `ac.sec_ratio_by_year` (note `averaging` in the row).
5. **Optional cross-definition line.** When both are available, show them
   side by side with the two definition strings; never average them.

## Output
A table (peer rows + target row highlighted), the definition line, the
vintage line (FDIC snapshot late 2022; SEC bulk fiscal 2019; EDGAR API
current), and receipts.
