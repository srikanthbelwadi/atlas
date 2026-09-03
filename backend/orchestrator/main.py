"""
Atlas orchestrator API (Cloud Run).

Three concerns, kept in one small FastAPI app per the plan's §08 access model:

  - `POST /ask`      — SSE stream of the live query trace, then the answer.
                        Requires a Firebase ID token for an *approved* user.
  - `GET  /healthz`   — Cloud Run liveness/readiness probe, no auth.
  - `/admin/*`        — the approval console's API: list users, approve/reject.
                        Requires a Firebase ID token whose email is in
                        ATLAS_ADMIN_EMAILS (defaults to the product owner).

Auth is Firebase Auth end to end: the frontend signs the user in with Google
Sign-In, sends the resulting ID token as `Authorization: Bearer <token>` on
every request, and this service verifies it with the Firebase Admin SDK —
no separate session/JWT scheme of our own.

New-user handling (plan §08): the first time a verified token's uid has no
`users/{uid}` doc, we create one with status="pending". A Firestore-triggered
Cloud Function (infra/functions/on_user_created, deployed separately) reacts
to that document creation to email the admin — kept out of the request path
here so a slow mail send never adds latency to the user's first sign-in.

Exception: any email listed in ATLAS_PREAPPROVED_EMAILS skips the queue
entirely and is marked "approved" immediately, on both the create path and
(for an email added to the list after that user's first sign-in) the
existing-doc path — see require_approved_user() below.
"""
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from firebase_admin import auth as firebase_auth, credentials, firestore as fb_firestore, initialize_app

from . import packs, pipeline
from .skills import filing_fact_check
from ..accessor import okf_loader

ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ATLAS_ADMIN_EMAILS", "srikanthbelwadi@gmail.com").split(",") if e.strip()}
# Accounts that skip the manual approval queue entirely — same allowlist
# shape as ADMIN_EMAILS, but these accounts still show up in the admin
# console as regular "approved" users, not admins. Empty by default so a
# fresh deploy without this env var behaves exactly as before.
PREAPPROVED_EMAILS = {e.strip().lower() for e in os.environ.get("ATLAS_PREAPPROVED_EMAILS", "").split(",") if e.strip()}
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ATLAS_ALLOWED_ORIGINS", "*").split(",") if o.strip()]

_fb_app = initialize_app()
_db = fb_firestore.client()

app = FastAPI(title="Atlas Orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


def _verify_token(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        return firebase_auth.verify_id_token(token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


def require_approved_user(authorization: str | None = Header(default=None)) -> dict:
    decoded = _verify_token(authorization)
    uid, email = decoded["uid"], decoded.get("email", "")
    preapproved = email.lower() in PREAPPROVED_EMAILS
    doc_ref = _db.collection("users").document(uid)
    snap = doc_ref.get()

    if not snap.exists:
        doc_ref.set({
            "uid": uid,
            "email": email,
            "display_name": decoded.get("name", ""),
            "status": "approved" if preapproved else "pending",
            "created_at": fb_firestore.SERVER_TIMESTAMP,
        })
        if preapproved:
            return {"uid": uid, "email": email}
        raise HTTPException(status_code=403, detail="Account created — waiting on admin approval.")

    status = snap.get("status")
    if status != "approved":
        # Covers a preapproved email that signed in (and got its doc created
        # as "pending") before ATLAS_PREAPPROVED_EMAILS included it — flips
        # it to approved on the next request instead of leaving it stuck
        # waiting for an admin who was never going to review it.
        if preapproved:
            doc_ref.set({"status": "approved"}, merge=True)
            return {"uid": uid, "email": email}
        raise HTTPException(status_code=403, detail=f"Account status: {status}. Waiting on admin approval.")

    return {"uid": uid, "email": email}


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    decoded = _verify_token(authorization)
    email = (decoded.get("email") or "").lower()
    if email not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access only.")
    return {"uid": decoded["uid"], "email": email}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def _resolve_pack(body: dict) -> str:
    """`pack` is optional and defaults to the public demo. A pack the deploy
    hasn't enabled (ATLAS_PACKS_ENABLED) is refused outright rather than
    silently answered from the public catalog — the finance frontend must
    never get a public-pack answer dressed up as a finance one."""
    pack = (body.get("pack") or packs.DEFAULT_PACK).strip().lower()
    if not packs.is_enabled(pack):
        raise HTTPException(status_code=400, detail=f"Unknown or disabled pack: {pack}")
    return pack


@app.post("/ask")
async def ask(request: Request, authorization: str | None = Header(default=None)):
    user = require_approved_user(authorization)
    body = await request.json()
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Missing 'question'")
    pack = _resolve_pack(body)

    async def event_stream():
        async for evt in pipeline.run(question, user["uid"], pack):
            yield {"event": evt["event"], "data": _json(evt["data"])}

    return EventSourceResponse(event_stream())


@app.post("/skills/filing-fact-check")
async def fact_check(request: Request, authorization: str | None = Header(default=None)):
    """Finance pack: verify every numeric claim in a paragraph against SEC
    filings through attested computations only. Same SSE stream shape as
    /ask, plus claim.* events; see skills/filing_fact_check.py."""
    user = require_approved_user(authorization)
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text'")
    if len(text) > 4000:
        raise HTTPException(status_code=400, detail="Paragraph is too long (4,000 characters max).")
    pack = _resolve_pack({"pack": body.get("pack") or "finance"})
    if pack != "finance":
        raise HTTPException(status_code=400, detail="Fact-check is only available in the finance pack.")

    async def event_stream():
        async for evt in filing_fact_check.run(text, user["uid"], pack):
            yield {"event": evt["event"], "data": _json(evt["data"])}

    return EventSourceResponse(event_stream())


_catalog_cache: dict[str, tuple[float, dict]] = {}


@app.get("/packs/{pack}/catalog")
def pack_catalog(pack: str, user: dict = Depends(require_approved_user)):
    """Everything discovery can see for one pack: crawled tables (from
    ard_catalog.embeddings metadata) and hand-authored OKF documents, each
    with its trust tier and, for reviewed templates, reviewer / freshness.
    This is what /finance/catalog renders. Cached five minutes in-process —
    it only changes on a crawl or a deploy."""
    import time
    if not packs.is_enabled(pack):
        raise HTTPException(status_code=404, detail=f"Unknown or disabled pack: {pack}")
    cached = _catalog_cache.get(pack)
    if cached and time.monotonic() - cached[0] < 300:
        return cached[1]

    entries = []
    for doc in okf_loader.load_all(pack=pack):
        runtime = (doc.computation or {}).get("runtime", {}) if doc.computation else {}
        entries.append({
            "id": doc.id, "title": doc.title, "description": doc.description, "type": doc.type, "kind": doc.source.get("kind"),
            "executor": doc.executor, "trust": doc.trust, **doc.governance(),
            "parameters": [{"name": p.get("name"), "type": p.get("type", "STRING"), "required": p.get("required", True),
                            "description": p.get("description", "")} for p in runtime.get("parameters", [])],
            "sql": runtime.get("sql"), "body": doc.body, "tags": doc.tags, "sources": doc.sources or [doc.source],
            "cost_profile": doc.cost_profile,
        })
    try:
        from google.cloud import bigquery
        from .discovery import ARD_CATALOG_DATASET, PROJECT_ID
        import json as _json_mod
        client = bigquery.Client(project=PROJECT_ID)
        sql = f"""
            SELECT doc_id, metadata, updated_at FROM `{PROJECT_ID}.{ARD_CATALOG_DATASET}.embeddings`
            WHERE COALESCE(JSON_VALUE(metadata, '$.pack'), JSON_VALUE(SAFE.PARSE_JSON(JSON_VALUE(metadata)), '$.pack'), '{packs.DEFAULT_PACK}') = @pack
            ORDER BY doc_id
        """
        job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("pack", "STRING", pack)]))
        for row in job.result(timeout=20):
            meta = row.metadata or {}
            for _ in range(2):  # unwrap a JSON string (possibly double-encoded) into a dict
                if isinstance(meta, str):
                    try:
                        meta = _json_mod.loads(meta)
                    except ValueError:
                        meta = {}
            if not isinstance(meta, dict):
                meta = {}
            entries.append({
                "id": row.doc_id, "title": meta.get("title", row.doc_id), "description": meta.get("description", ""),
                "type": meta.get("type", "Table"), "kind": "bigquery", "executor": None, "trust": meta.get("trust", "machine-confirmed"),
                "pack": pack, "reviewer": None, "reviewed_on": None, "stale_after": None, "stale": False, "lifecycle": "active",
                "version": None, "row_count": meta.get("row_count"), "size_gb": meta.get("size_gb"), "large_table": meta.get("large_table"),
                "source": meta.get("source"), "updated_at": str(row.updated_at),
            })
    except Exception as exc:  # noqa: BLE001 — catalog page still shows the OKF half if BigQuery is unreachable
        print(f"[catalog] crawled rows unavailable for pack {pack}: {exc}")

    result = {"pack": packs.info(pack), "entries": entries,
              "counts": {"attested": sum(1 for e in entries if e["type"] == "AttestedComputation"),
                         "tables": sum(1 for e in entries if e["type"] == "Table")}}
    _catalog_cache[pack] = (time.monotonic(), result)
    return result


def _json(data: dict) -> str:
    import json
    return json.dumps(data, default=str)


# --- admin console API -------------------------------------------------

@app.get("/admin/users")
def list_users(admin: dict = Depends(require_admin)):
    docs = _db.collection("users").order_by("created_at", direction=fb_firestore.Query.DESCENDING).stream()
    return {"users": [d.to_dict() | {"id": d.id} for d in docs]}


@app.post("/admin/users/{uid}/approve")
def approve_user(uid: str, admin: dict = Depends(require_admin)):
    _db.collection("users").document(uid).set({"status": "approved"}, merge=True)
    return {"ok": True}


@app.post("/admin/users/{uid}/reject")
def reject_user(uid: str, admin: dict = Depends(require_admin)):
    _db.collection("users").document(uid).set({"status": "rejected"}, merge=True)
    return {"ok": True}


@app.get("/admin/usage/{uid}")
def usage_for_user(uid: str, admin: dict = Depends(require_admin)):
    import datetime as dt
    month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    snap = _db.collection("usage").document(f"{uid}_{month}").get()
    return snap.to_dict() if snap.exists else {"estimated_cost_usd": 0.0, "query_count": 0}
