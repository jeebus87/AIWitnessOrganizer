"""Test health endpoint"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create test client"""
    with TestClient(app) as c:
        yield c


def test_health_check(client):
    """Test health endpoint returns healthy status"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_root(client):
    """Test root endpoint returns API info"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "AI Witness Finder API"
