"""Pytest setup: isolated temp SQLite DB, seeded once, shared TestClient.

Env vars are set BEFORE importing the app so config picks them up.
"""
import os
import sys
import tempfile

_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _db_path.replace("\\", "/")
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "whsec_test_123"
os.environ["RAZORPAY_KEY_ID"] = ""  # force mock mode for payment links
os.environ["GEMINI_API_KEY"] = ""   # force LLM off so tests stay offline & deterministic

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import seed as seed_module  # noqa: E402
import main  # noqa: E402

seed_module.seed()  # populate the temp DB once

WEBHOOK_SECRET = b"whsec_test_123"


@pytest.fixture(scope="session")
def client():
    return TestClient(main.app)


@pytest.fixture(scope="session")
def buyer(client):
    r = client.post("/api/auth/login", json={"email": "buyer@test.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def merchant_b(client):
    r = client.post("/api/auth/login", json={"email": "b@workspacedirect.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def merchant_a(client):
    r = client.post("/api/auth/login", json={"email": "a@comfortseating.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def pytest_sessionfinish(session, exitstatus):
    try:
        os.remove(_db_path)
    except OSError:
        pass
