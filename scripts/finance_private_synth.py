#!/usr/bin/env python3
"""
Synthetic stand-in for the two Kaggle datasets behind use case D.

Writes four CSVs with the SAME column names (a subset) as the real files, so
scripts/finance_private_load.sh and infra/finance/private_setup.sql work
unchanged on either the Kaggle originals or these:

    application_train.csv     (Home Credit Default Risk — applications)
    bureau.csv                (Home Credit — bureau history)
    installments_payments.csv (Home Credit — instalment schedule vs payments)
    paysim.csv                (PaySim — payments ledger)

Why this exists: the Kaggle originals need a Kaggle account and a 2.5 GB
download; the demo needs the *shape* of an internal risk mart, not those
particular rows. Everything here is generated from a fixed seed with
deliberately planted structure so the templates have something to find:
default rates that rise with bureau inquiries and fall with income, late
payment that clusters in the months just before application, and a handful
of accounts doing repeated just-under-threshold transfers (structuring) in
the ledger. No real person or account is represented.

    python3 scripts/finance_private_synth.py --out ~/Documents/ARD_UKF/data/finance_demo
    python3 scripts/finance_private_synth.py --out ... --applications 50000 --transactions 400000
"""
import argparse
import csv
import os
import random

CONTRACT_TYPES = [("Cash loans", 0.905), ("Revolving loans", 0.095)]
INCOME_TYPES = [("Working", 0.52), ("Commercial associate", 0.23), ("Pensioner", 0.18), ("State servant", 0.07)]
EDUCATION = [("Secondary / secondary special", 0.71), ("Higher education", 0.24), ("Incomplete higher", 0.03), ("Lower secondary", 0.02)]
FAMILY = [("Married", 0.64), ("Single / not married", 0.15), ("Civil marriage", 0.10), ("Separated", 0.06), ("Widow", 0.05)]
HOUSING = [("House / apartment", 0.89), ("With parents", 0.05), ("Municipal apartment", 0.04), ("Rented apartment", 0.02)]
OCCUPATION = [("Laborers", 0.26), ("Sales staff", 0.15), ("Core staff", 0.13), ("Managers", 0.10), ("Drivers", 0.09),
              ("High skill tech staff", 0.05), ("Accountants", 0.05), ("Medicine staff", 0.04), ("", 0.13)]
CREDIT_STATUS = [("Closed", 0.63), ("Active", 0.35), ("Sold", 0.015), ("Bad debt", 0.005)]
CREDIT_TYPES = [("Consumer credit", 0.73), ("Credit card", 0.23), ("Car loan", 0.02), ("Mortgage", 0.01), ("Microloan", 0.01)]
TXN_TYPES = [("CASH_OUT", 0.35), ("PAYMENT", 0.34), ("CASH_IN", 0.22), ("TRANSFER", 0.08), ("DEBIT", 0.01)]


def pick(rng, table):
    r = rng.random()
    acc = 0.0
    for value, p in table:
        acc += p
        if r <= acc:
            return value
    return table[-1][0]


def applications(rng, n, out):
    """Default probability is a logistic-ish function of income band, bureau
    inquiries, education and region rating — the relationships the two
    Home Credit templates exist to surface."""
    rows = []
    with open(os.path.join(out, "application_train.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SK_ID_CURR", "TARGET", "NAME_CONTRACT_TYPE", "CODE_GENDER", "AMT_INCOME_TOTAL", "AMT_CREDIT", "AMT_ANNUITY",
                    "NAME_INCOME_TYPE", "NAME_EDUCATION_TYPE", "NAME_FAMILY_STATUS", "NAME_HOUSING_TYPE", "OCCUPATION_TYPE",
                    "REGION_RATING_CLIENT", "DAYS_BIRTH", "AMT_REQ_CREDIT_BUREAU_YEAR", "AMT_REQ_CREDIT_BUREAU_QRT",
                    "EXT_SOURCE_2", "EXT_SOURCE_3"])
        for i in range(n):
            sk = 100002 + i
            income = round(max(25000, rng.lognormvariate(11.9, 0.45)), -2)
            credit = round(max(45000, income * rng.uniform(1.5, 6.0)), -3)
            annuity = round(credit / rng.uniform(12, 40), 1)
            income_type = pick(rng, INCOME_TYPES)
            education = pick(rng, EDUCATION)
            region = rng.choices([1, 2, 3], weights=[0.10, 0.74, 0.16])[0]
            inquiries_year = rng.choices([0, 1, 2, 3, 4, 5, 6, 8], weights=[26, 27, 18, 12, 7, 4, 3, 3])[0]
            inquiries_qrt = min(inquiries_year, rng.choices([0, 1, 2, 3], weights=[72, 20, 6, 2])[0])
            ext2 = min(0.95, max(0.02, rng.gauss(0.52, 0.19)))
            ext3 = min(0.95, max(0.02, rng.gauss(0.51, 0.19)))
            age_days = -int(rng.uniform(21, 68) * 365.25)
            # planted structure
            p = 0.045
            p += {0: -0.006, 1: 0.0, 2: 0.006, 3: 0.014, 4: 0.022, 5: 0.03, 6: 0.04, 8: 0.05}[inquiries_year]
            p += 0.012 if income < 100000 else (0.004 if income < 150000 else (-0.004 if income < 225000 else -0.012))
            p += {"Higher education": -0.02, "Incomplete higher": 0.0, "Lower secondary": 0.03}.get(education, 0.01)
            p += {1: -0.02, 2: 0.0, 3: 0.03}[region]
            p += -0.06 * (ext2 + ext3 - 1.03)
            p += 0.015 if income_type == "Working" else (-0.02 if income_type == "Pensioner" else 0.0)
            target = 1 if rng.random() < max(0.01, p) else 0
            w.writerow([sk, target, pick(rng, CONTRACT_TYPES), rng.choices(["F", "M"], weights=[66, 34])[0], income, credit, annuity,
                        income_type, education, pick(rng, FAMILY), pick(rng, HOUSING), pick(rng, OCCUPATION), region, age_days,
                        inquiries_year, inquiries_qrt, round(ext2, 4), round(ext3, 4)])
            rows.append((sk, target, inquiries_year))
    return rows


def bureau(rng, apps, out):
    """Number of prior credits correlates with inquiries; defaulters carry
    more overdue history."""
    bureau_id = 5000000
    with open(os.path.join(out, "bureau.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SK_ID_CURR", "SK_ID_BUREAU", "CREDIT_ACTIVE", "CREDIT_TYPE", "DAYS_CREDIT", "CREDIT_DAY_OVERDUE",
                    "AMT_CREDIT_SUM", "AMT_CREDIT_SUM_DEBT", "AMT_CREDIT_SUM_OVERDUE", "CNT_CREDIT_PROLONG"])
        for sk, target, inq in apps:
            n_prior = max(0, int(rng.gauss(2.5 + 0.6 * inq + (1.2 if target else 0), 2.5)))
            for _ in range(n_prior):
                bureau_id += 1
                status = pick(rng, CREDIT_STATUS)
                amount = round(max(5000, rng.lognormvariate(11.5, 1.1)), -2)
                debt = round(amount * rng.uniform(0, 0.8), -2) if status == "Active" else 0
                overdue_days = 0
                overdue_amt = 0
                if status in ("Active", "Bad debt") and rng.random() < (0.12 if target else 0.03):
                    overdue_days = rng.choice([5, 12, 30, 45, 60, 90, 120])
                    overdue_amt = round(min(debt, amount * rng.uniform(0.02, 0.3)), -1)
                w.writerow([sk, bureau_id, status, pick(rng, CREDIT_TYPES), -rng.randint(30, 2900), overdue_days, amount, debt,
                            overdue_amt, rng.choices([0, 1, 2], weights=[95, 4, 1])[0]])


def installments(rng, apps, out, per_applicant):
    """Late payment is more common for defaulters and in the 1–6 months
    before the current application (a deteriorating vintage)."""
    prev_id = 1000000
    with open(os.path.join(out, "installments_payments.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SK_ID_CURR", "SK_ID_PREV", "NUM_INSTALMENT_NUMBER", "DAYS_INSTALMENT", "DAYS_ENTRY_PAYMENT", "AMT_INSTALMENT", "AMT_PAYMENT"])
        for sk, target, _ in apps:
            n_loans = rng.choices([0, 1, 2, 3], weights=[15, 45, 28, 12])[0]
            for _ in range(n_loans):
                prev_id += 1
                n_inst = rng.randint(4, per_applicant)
                start = -rng.randint(60, 2500)
                amount = round(max(1500, rng.lognormvariate(9.2, 0.7)), 2)
                for k in range(1, n_inst + 1):
                    due = start + 30 * k
                    if due > -1:
                        break
                    months_before = -due / 30.4375
                    p_late = 0.06 + (0.10 if target else 0.0) + (0.06 if months_before <= 6 else 0.0)
                    late = rng.choice([1, 2, 3, 5, 8, 14, 30]) if rng.random() < p_late else -rng.randint(0, 20)
                    paid = amount if rng.random() > (0.08 if target else 0.03) else round(amount * rng.uniform(0.1, 0.95), 2)
                    w.writerow([sk, prev_id, k, due, due + late, amount, paid])


def paysim(rng, n, out):
    """A payments ledger with ~0.13% fraud, the legacy >200k flag rule, and
    twelve planted structuring accounts that send repeated transfers just
    under 10,000 within a few hours."""
    with open(os.path.join(out, "paysim.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["step", "type", "amount", "nameOrig", "oldbalanceOrg", "newbalanceOrig", "nameDest", "oldbalanceDest", "newbalanceDest", "isFraud", "isFlaggedFraud"])
        for _ in range(n):
            step = rng.randint(1, 743)
            ttype = pick(rng, TXN_TYPES)
            amount = round(max(1.0, rng.lognormvariate(9.5 if ttype in ("TRANSFER", "CASH_OUT") else 8.0, 1.4)), 2)
            fraud = 1 if ttype in ("TRANSFER", "CASH_OUT") and rng.random() < 0.003 else 0
            orig_before = round(max(0.0, rng.lognormvariate(9.0, 2.0)), 2) if rng.random() > 0.3 else 0.0
            orig_after = max(0.0, orig_before - amount) if ttype != "CASH_IN" else orig_before + amount
            dest = f"M{rng.randint(10**8, 10**9)}" if ttype == "PAYMENT" else f"C{rng.randint(10**8, 10**9)}"
            dest_before = 0.0 if ttype == "PAYMENT" else round(max(0.0, rng.lognormvariate(11.0, 2.0)), 2)
            dest_after = dest_before if ttype == "PAYMENT" else dest_before + amount
            w.writerow([step, ttype, amount, f"C{rng.randint(10**8, 10**9)}", orig_before, round(orig_after, 2), dest, dest_before,
                        round(dest_after, 2), fraud, 1 if ttype == "TRANSFER" and amount > 200000 else 0])
        # planted structuring: repeated just-under-threshold transfers within a short window
        for j in range(12):
            acct = f"C{700000000 + j}"
            dest = f"C{800000000 + j}"
            start = rng.randint(1, 700)
            n_txn = rng.randint(4, 9)
            bal = 90000.0
            for k in range(n_txn):
                amount = round(rng.uniform(9100, 9950), 2)
                step = start + rng.randint(0, 40)
                w.writerow([step, "TRANSFER", amount, acct, round(bal, 2), round(bal - amount, 2), dest, 0.0, 0.0, 1 if rng.random() < 0.5 else 0, 0])
                bal -= amount


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--applications", type=int, default=60000)
    ap.add_argument("--transactions", type=int, default=400000)
    ap.add_argument("--installments-per-loan", type=int, default=24)
    ap.add_argument("--seed", type=int, default=20260904)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(args.seed)
    apps = applications(rng, args.applications, args.out)
    bureau(rng, apps, args.out)
    installments(rng, apps, args.out, args.installments_per_loan)
    paysim(rng, args.transactions, args.out)
    for name in ("application_train.csv", "bureau.csv", "installments_payments.csv", "paysim.csv"):
        path = os.path.join(args.out, name)
        with open(path) as f:
            n = sum(1 for _ in f) - 1
        print(f"{name}: {n:,} rows, {os.path.getsize(path)/1e6:.1f} MB")


if __name__ == "__main__":
    main()
