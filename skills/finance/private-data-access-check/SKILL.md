---
name: private-data-access-check
description: Verify, for an Atlas account, exactly which private finance-pack sources it can and cannot query — and demonstrate the enforcement by asking an internal-data question and reading the withheld card — before an agent plans a workflow that depends on internal data.
---

# Private data access check

## When to use
Before any workflow that touches the internal risk mart; when a user
reports "Atlas won't answer my internal question"; in a demo, to show the
"your controls still apply" moment.

## Procedure
1. **Catalog view.** `GET /packs/finance/catalog`. Read `entitlements`
   (this account's grants) and, per entry, `visibility`, `entitlement`,
   `accessible`, `restricted_to`. List the private entries in two columns:
   accessible / withheld. For a withheld entry the response deliberately
   omits `sql` and `body`.
2. **Live enforcement.** `POST /ask` {pack: finance} "What is our default
   rate by income band?" Expect one of:
   - entitled: `answer` with `receipt.visibility = "private"` and
     `receipt.unlocked_by = "finance.internal"`, plus `answer.access`
     naming the entitlement;
   - not entitled: `guardrail.blocked {code: not_entitled}` then `answer`
     with `refused: "not_entitled"`, `citations: []`, and
     `access.withheld[]` naming the sources (ids and titles only). The
     trace's discover line says the best match was withheld and that Atlas
     will not substitute a public stand-in.
3. **Public unaffected.** Ask a public finance question ("Complaints per
   $1B of deposits for the ten largest banks in 2022") and confirm it
   answers identically for both kinds of account — entitlement changes
   nothing outside the private sources.
4. **Fixing access.** Only an admin can grant an entitlement: the toggle on
   `/admin` (or `scripts/finance_entitle.py <email> --grant
   finance.internal`). It takes effect on the user's next request. The
   skill reports *who to ask*, it never attempts to escalate.

## Output
A short access report: account, entitlements held, private sources
accessible vs withheld, the outcome of the live check with the receipt or
the withheld list, and the admin step if access is missing.
