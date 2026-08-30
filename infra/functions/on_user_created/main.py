"""
Firestore-triggered Cloud Function: emails ATLAS_ADMIN_EMAILS whenever a new
`users/{uid}` document is created with status="pending" — the notification
step referenced in backend/orchestrator/main.py's docstring and flagged as
"not yet built" in infra/README.md's "Still to design/build" list, now
wired up.

Deployed separately from the orchestrator (its own runtime, its own deploy
command — see infra/README.md) because a Firestore trigger has nothing in
common with the request path of `POST /ask`, and keeping it out of that path
means a slow or failing mail send can never add latency or a failure mode to
a user's actual sign-in — exactly the reasoning `main.py`'s docstring already
gives for keeping this out-of-band.

Preapproved emails (ATLAS_PREAPPROVED_EMAILS) never trigger a notification:
main.py's require_approved_user() writes status="approved" directly for
them on the create path, so their user doc is never created in the
"pending" state this function listens for — there's nothing for an admin to
act on, so nothing to email about.
"""
import os
import smtplib
from email.mime.text import MIMEText

from firebase_functions import firestore_fn, options

# Same allowlist shape as backend/orchestrator/main.py's ADMIN_EMAILS — kept
# as this function's own env var rather than shared code, since it deploys
# and scales completely independently of the orchestrator (different
# runtime, different trigger type, different failure domain).
ADMIN_EMAILS = [
    e.strip() for e in os.environ.get("ATLAS_ADMIN_EMAILS", "srikanthbelwadi@gmail.com").split(",") if e.strip()
]

# SMTP transport config. ATLAS_SMTP_PASSWORD is meant to be set as a Secret
# Manager-backed secret (`firebase functions:secrets:set ATLAS_SMTP_PASSWORD`)
# per infra/README.md's deploy instructions, never a plain env var — the
# other three are non-secret and fine as plain config.
SMTP_HOST = os.environ.get("ATLAS_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("ATLAS_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("ATLAS_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("ATLAS_SMTP_PASSWORD", "")
FROM_ADDRESS = os.environ.get("ATLAS_SMTP_FROM", SMTP_USER)

ADMIN_CONSOLE_URL = os.environ.get(
    "ATLAS_ADMIN_CONSOLE_URL", "https://atlas-web--atlas-ard-okf.us-central1.hosted.app/admin"
)


@firestore_fn.on_document_created(
    document="users/{uid}",
    region=os.environ.get("VERTEX_LOCATION", "us-central1"),
    secrets=["ATLAS_SMTP_PASSWORD"],
)
def on_user_created(event: firestore_fn.Event[firestore_fn.DocumentSnapshot | None]) -> None:
    """Fires once per new users/{uid} doc. Only a doc created as "pending"
    needs a notification — one created "approved" (an ATLAS_ADMIN_EMAILS or
    ATLAS_PREAPPROVED_EMAILS account signing in for the first time) needs no
    admin action, so this is a deliberate no-op for those, not a missed
    case."""
    snap = event.data
    if snap is None:
        return
    data = snap.to_dict() or {}
    if data.get("status") != "pending":
        return

    uid = event.params.get("uid", "")
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD and ADMIN_EMAILS):
        # No mail transport configured yet (fresh deploy before the SMTP
        # secret is set, or a deploy that intentionally skips email). Log
        # and return rather than raise — a missing secret should never turn
        # into a retried or permanently failing function execution, and the
        # admin console already lists this user as "pending" regardless of
        # whether the email goes out. This is a convenience notification,
        # not the only way an admin finds out about a new signup.
        print(f"[on_user_created] SMTP not configured — skipping notification for uid={uid}")
        return

    email = data.get("email", "(no email on record)")
    name = data.get("display_name", "")
    subject = f"Atlas: new sign-up waiting on approval ({email})"
    body = (
        "A new account is waiting for approval.\n\n"
        f"Email: {email}\n"
        f"Name: {name or '(not provided)'}\n"
        f"UID: {uid}\n\n"
        f"Approve or reject it here: {ADMIN_CONSOLE_URL}\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_ADDRESS
    msg["To"] = ", ".join(ADMIN_EMAILS)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_ADDRESS, ADMIN_EMAILS, msg.as_string())
    except Exception as exc:  # noqa: BLE001 — the Firestore write already
        # succeeded regardless of whether this email goes out; a mail-server
        # hiccup should be logged, not surfaced as a function failure that
        # Cloud Functions would otherwise retry indefinitely.
        print(f"[on_user_created] failed to send admin notification for uid={uid}: {exc!r}")
