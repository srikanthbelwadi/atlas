#!/usr/bin/env bash
# Prints a Firebase ID token for an approved user, for scripts/golden_run.py.
# Uses the Identity Toolkit REST API with the web API key from apphosting.yaml
# and an email/password account — enable Email/Password sign-in in the
# Firebase console for a dedicated test account first (Google sign-in can't
# be scripted), approve it once in /admin, then:
#   ATLAS_TEST_EMAIL=... ATLAS_TEST_PASSWORD=... scripts/firebase_token.sh
set -euo pipefail
API_KEY=${FIREBASE_API_KEY:-$(grep -A1 NEXT_PUBLIC_FIREBASE_API_KEY frontend/apphosting.yaml | grep value | awk '{print $2}')}
curl -s "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${API_KEY}" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ATLAS_TEST_EMAIL}\",\"password\":\"${ATLAS_TEST_PASSWORD}\",\"returnSecureToken\":true}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["idToken"])'
