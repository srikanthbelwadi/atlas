"""
The one metric-to-XBRL-tag map, shared by every path that reads SEC data.

Two executors read the same facts from two independent sources — the SEC
EDGAR `company-facts` API (sec_edgar_accessor.py) and the SEC Financial
Statement Data Sets mirrored in `bigquery-public-data.sec_quarterly_financials`
(the `ac.sec_fact_from_bq` Attested Computation). If each carried its own
tag list they would drift, and a "reconciliation" between them would
silently compare two different definitions. So the map lives here, once,
and both import it; the OKF documents for both computations cite this file
as their definition of record.

Every entry is a real, well-established US-GAAP/DEI concept chosen and
reviewed by a person (the same trust story as the Attested Computation
templates). `candidates` is ordered: the first tag is the canonical one, the
rest are the alternates filers have migrated to or from (ASC 606 revenue is
the classic case). `period` is "duration" (income-statement / cash-flow
flows, reported for a fiscal year) or "instant" (balance-sheet stocks, at
the fiscal year end) — the two need different annual-fact selection rules.

Bank-specific lines (deposits, loans, net interest income, provision) exist
because use case B's peer questions are about banks; a non-bank that never
reports one of these correctly returns "no data", never a wrong number.
"""

# key -> (taxonomy, candidate tags, unit, period kind, plain-language definition)
CURATED_METRICS: dict[str, tuple[str, tuple[str, ...], str, str, str]] = {
    # --- income statement (duration) ---
    "revenue": (
        "us-gaap",
        (
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ),
        "USD", "duration",
        "Total revenues as reported; ASC 606 filers report under RevenueFromContractWithCustomer…",
    ),
    "net_income": ("us-gaap", ("NetIncomeLoss",), "USD", "duration", "Net income (loss) attributable to the parent"),
    "operating_income": ("us-gaap", ("OperatingIncomeLoss",), "USD", "duration", "Operating income (loss)"),
    "interest_expense": ("us-gaap", ("InterestExpense",), "USD", "duration", "Total interest expense"),
    "income_tax_expense": ("us-gaap", ("IncomeTaxExpenseBenefit",), "USD", "duration", "Income tax expense (benefit)"),
    "net_interest_income": (
        "us-gaap",
        ("InterestIncomeExpenseNet", "InterestIncomeExpenseAfterProvisionForLoanLoss"),
        "USD", "duration",
        "Net interest income (banks): interest income less interest expense, before provision",
    ),
    "provision_for_credit_losses": (
        "us-gaap",
        ("ProvisionForLoanLeaseAndOtherLosses", "ProvisionForLoanLossesExpensed", "ProvisionForCreditLosses"),
        "USD", "duration",
        "Provision for credit/loan losses (banks)",
    ),
    "noninterest_expense": ("us-gaap", ("NoninterestExpense",), "USD", "duration", "Total noninterest expense (banks)"),
    "noninterest_income": ("us-gaap", ("NoninterestIncome",), "USD", "duration", "Total noninterest income (banks)"),
    "eps_diluted": ("us-gaap", ("EarningsPerShareDiluted",), "USD/shares", "duration", "Diluted earnings per share"),
    "dividends_declared_per_share": (
        "us-gaap", ("CommonStockDividendsPerShareDeclared",), "USD/shares", "duration",
        "Common dividends declared per share",
    ),
    # --- cash flow (duration) ---
    "operating_cash_flow": (
        "us-gaap", ("NetCashProvidedByUsedInOperatingActivities",), "USD", "duration",
        "Net cash provided by (used in) operating activities",
    ),
    "capital_expenditures": (
        "us-gaap", ("PaymentsToAcquirePropertyPlantAndEquipment",), "USD", "duration",
        "Payments to acquire property, plant and equipment",
    ),
    # --- balance sheet (instant, at fiscal year end) ---
    "total_assets": ("us-gaap", ("Assets",), "USD", "instant", "Total assets at fiscal year end"),
    "total_liabilities": ("us-gaap", ("Liabilities",), "USD", "instant", "Total liabilities at fiscal year end"),
    "stockholders_equity": (
        "us-gaap",
        ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        "USD", "instant",
        "Total stockholders' equity at fiscal year end",
    ),
    "cash_and_equivalents": (
        "us-gaap",
        ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
        "USD", "instant",
        "Cash and cash equivalents at fiscal year end",
    ),
    "deposits": ("us-gaap", ("Deposits",), "USD", "instant", "Total deposits at fiscal year end (banks)"),
    "loans": (
        "us-gaap",
        ("LoansAndLeasesReceivableNetReportedAmount", "NotesReceivableNet", "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss"),
        "USD", "instant",
        "Net loans and leases at fiscal year end (banks)",
    ),
    "long_term_debt": ("us-gaap", ("LongTermDebt", "LongTermDebtNoncurrent"), "USD", "instant", "Long-term debt at fiscal year end"),
    "shares_outstanding": ("dei", ("EntityCommonStockSharesOutstanding",), "shares", "instant", "Common shares outstanding (cover page)"),
}

# Ratios: numerator / denominator over curated metric keys, with the
# averaging rule spelled out so the answer can name it. `avg_denominator`
# means (this year-end + prior year-end) / 2 — the textbook definition, and
# explicitly NOT the FDIC quarterly-average definition, which is a different
# number by construction (see ac.fdic_peer_ratios).
CURATED_RATIOS: dict[str, dict] = {
    "roa": {"numerator": "net_income", "denominator": "total_assets", "avg_denominator": True,
            "definition": "Net income ÷ average total assets (two fiscal year-ends), from XBRL filings"},
    "roe": {"numerator": "net_income", "denominator": "stockholders_equity", "avg_denominator": True,
            "definition": "Net income ÷ average stockholders' equity (two fiscal year-ends), from XBRL filings"},
    "net_margin": {"numerator": "net_income", "denominator": "revenue", "avg_denominator": False,
                   "definition": "Net income ÷ revenue"},
    "efficiency_ratio": {"numerator": "noninterest_expense", "denominator": "net_interest_income", "avg_denominator": False,
                         "extra_denominator": "noninterest_income",
                         "definition": "Noninterest expense ÷ (net interest income + noninterest income) — banks"},
    "equity_to_assets": {"numerator": "stockholders_equity", "denominator": "total_assets", "avg_denominator": False,
                         "definition": "Stockholders' equity ÷ total assets at fiscal year end"},
}


def metric_keys() -> list[str]:
    return sorted(CURATED_METRICS)


def ratio_keys() -> list[str]:
    return sorted(CURATED_RATIOS)


def legacy_view() -> dict[str, tuple[str, tuple[str, ...], str]]:
    """The (taxonomy, tags, unit) triple shape sec_edgar_accessor.py has always
    used — kept so its fetch_metric() body didn't need to change."""
    return {k: (v[0], v[1], v[2]) for k, v in CURATED_METRICS.items()}


def tags_for(metric: str) -> tuple[str, ...]:
    return CURATED_METRICS[metric][1]


def period_kind(metric: str) -> str:
    return CURATED_METRICS[metric][3]


def definition(metric: str) -> str:
    return CURATED_METRICS[metric][4]
