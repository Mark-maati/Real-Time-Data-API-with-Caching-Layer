import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from contextlib import asynccontextmanager


@pytest.mark.asyncio
async def test_health(client):
    # Mock the DB engine.connect() used by the health endpoint
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    @asynccontextmanager
    async def mock_connect():
        yield mock_conn

    with patch("app.routers.admin.engine") as mock_engine, \
         patch("app.routers.admin.ping_redis", new_callable=AsyncMock, return_value=True):
        mock_engine.connect = mock_connect
        r = await client.get("/admin/health")
    assert r.status_code == 200
    assert r.json()["version"] is not None


@pytest.mark.asyncio
async def test_aggregate_empty(client):
    r = await client.get("/api/v1/aggregate")
    assert r.status_code == 200
    assert r.json()["total_records"] == 0


@pytest.mark.asyncio
async def test_records_pagination(client):
    r = await client.get("/api/v1/records?page=1&page_size=10")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data and "items" in data


@pytest.mark.asyncio
async def test_record_not_found(client):
    r = await client.get("/api/v1/records/99999")
    assert r.status_code == 404
    assert r.json()["error"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_cache_bust(client):
    r = await client.delete("/admin/cache")
    assert r.status_code == 204
