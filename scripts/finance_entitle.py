#!/usr/bin/env python3
"""
Grant or revoke a data entitlement on an Atlas user (Firestore users/{uid}).

    python3 scripts/finance_entitle.py atlas-test@atlasdata.world --grant finance.internal
    python3 scripts/finance_entitle.py atlas-test@atlasdata.world --revoke finance.internal
    python3 scripts/finance_entitle.py atlas-test@atlasdata.world            # show

Same effect as the toggle on /admin. Uses Application Default Credentials
(gcloud auth application-default login) and needs google-cloud-firestore:
    .venv/bin/pip install google-cloud-firestore
"""
import argparse
import os
import sys

from google.cloud import firestore

PROJECT = os.environ.get("PROJECT", "atlas-ard-okf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("email")
    ap.add_argument("--grant", action="append", default=[])
    ap.add_argument("--revoke", action="append", default=[])
    args = ap.parse_args()
    db = firestore.Client(project=PROJECT)
    docs = list(db.collection("users").where("email", "==", args.email.lower()).stream())
    if not docs:
        docs = list(db.collection("users").where("email", "==", args.email).stream())
    if not docs:
        print(f"no users/ document for {args.email} — the user must sign in once first (that creates it)")
        sys.exit(1)
    for d in docs:
        data = d.to_dict()
        ents = set(data.get("entitlements") or [])
        ents |= set(args.grant)
        ents -= set(args.revoke)
        if args.grant or args.revoke:
            d.reference.set({"entitlements": sorted(ents)}, merge=True)
        print(f"{d.id}  {data.get('email')}  status={data.get('status')}  entitlements={sorted(ents)}")


if __name__ == "__main__":
    main()
