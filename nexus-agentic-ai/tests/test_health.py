import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Test root welcome endpoint."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "version" in data


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test general health endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "nexus-backend"
    assert "timestamp" in data
    assert "X-Process-Time-Ms" in response.headers


@pytest.mark.asyncio
async def test_readiness_probe(client: AsyncClient):
    """Test readiness check probe."""
    response = await client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "components" in data
    assert data["components"]["safety_gate"] in ["active", "advisory"]


@pytest.mark.asyncio
async def test_liveness_probe(client: AsyncClient):
    """Test liveness probe."""
    response = await client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
