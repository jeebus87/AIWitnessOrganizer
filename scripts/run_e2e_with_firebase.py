#!/usr/bin/env python3
"""
Run E2E test by generating a Firebase token and calling the API.
"""
import asyncio
import os
import sys
import json
import httpx

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, auth

# Railway env vars (will be injected by railway run)
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "aiwitness-finder")
FIREBASE_CLIENT_EMAIL = os.environ.get("FIREBASE_CLIENT_EMAIL")
FIREBASE_PRIVATE_KEY = os.environ.get("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n")

API_URL = "https://aiwitnessfinder-api-production.up.railway.app"


def get_firebase_token():
    """Generate a Firebase ID token using Admin SDK."""
    # Initialize Firebase Admin if not already done
    if not firebase_admin._apps:
        cred_dict = {
            "type": "service_account",
            "project_id": FIREBASE_PROJECT_ID,
            "private_key": FIREBASE_PRIVATE_KEY,
            "client_email": FIREBASE_CLIENT_EMAIL,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)

    # Get the first user from the database to impersonate
    # We need a real user UID
    print("Getting user from database...")

    # Use sqlalchemy to get a user
    from sqlalchemy import create_engine, text

    db_url = os.environ.get("DATABASE_URL", "").replace("postgresql://", "postgresql+psycopg2://")
    if "railway.internal" in db_url:
        # Use public URL
        db_url = "postgresql+psycopg2://postgres:TqleRXzeSFzGyUHMSWnhayeFECfXHwwh@interchange.proxy.rlwy.net:41696/railway"

    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT firebase_uid FROM users WHERE firebase_uid IS NOT NULL LIMIT 1"))
        row = result.fetchone()
        if not row:
            print("No users found in database!")
            return None
        firebase_uid = row[0]
        print(f"Found user with Firebase UID: {firebase_uid}")

    # Create a custom token for this user
    custom_token = auth.create_custom_token(firebase_uid)
    print(f"Created custom token")

    # Exchange custom token for ID token using Firebase REST API
    api_key = os.environ.get("FIREBASE_API_KEY", "AIzaSyDARGN0xurmAH7pV6zle-rCE-jteStq730")

    response = httpx.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={api_key}",
        json={
            "token": custom_token.decode() if isinstance(custom_token, bytes) else custom_token,
            "returnSecureToken": True
        }
    )

    if response.status_code != 200:
        print(f"Failed to exchange token: {response.text}")
        return None

    data = response.json()
    id_token = data.get("idToken")
    print(f"Got ID token (length: {len(id_token) if id_token else 0})")

    return id_token


def run_e2e_test(token: str):
    """Call the E2E test endpoint."""
    print(f"\nCalling E2E test endpoint...")

    response = httpx.post(
        f"{API_URL}/api/v1/test/e2e",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        timeout=300  # 5 minutes timeout
    )

    print(f"Response status: {response.status_code}")

    if response.status_code == 200:
        result = response.json()
        print("\n" + "="*60)
        print("E2E TEST RESULTS")
        print("="*60)
        print(json.dumps(result, indent=2))

        if result.get("passed"):
            print("\n✓ ALL TESTS PASSED!")
            return True
        else:
            print("\n✗ SOME TESTS FAILED")
            return False
    else:
        print(f"Error: {response.text}")
        return False


def main():
    print("="*60)
    print("E2E TEST: Generating Firebase token and calling API")
    print("="*60)

    token = get_firebase_token()
    if not token:
        print("Failed to get Firebase token")
        sys.exit(1)

    success = run_e2e_test(token)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
