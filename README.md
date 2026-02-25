# Real-Time Data Aggregation API

A FastAPI service that fetches, aggregates, and caches data from multiple external sources with stale-while-revalidate caching, circuit breaker protection, and scheduled background refresh.

## Architecture

```
Client --> [Rate Limiter] --> [Auth] --> FastAPI Routers
                                            |
                        +-------------------+-----------------+
                        |                   |                 |
                   Data Router         Admin Router      Scheduler
                        |                   |                 |
                   Aggregator          Health/Metrics    Periodic Refresh
                        |                   |                 |
                +-------+-------+      +----+----+           |
                |               |      |         |           |
            Cache (Redis)    Fetcher   DB Check  Redis Ping  |
                             /     \                         |
                       Circuit      HTTP + Retry  <----------+
                       Breaker      (tenacity)
                             \     /
                          Repositories
                               |
                         PostgreSQL (asyncpg)
```

**Key components:**

- **PostgreSQL** -- persistent storage for fetched records and audit logs
- **Redis** -- stale-while-revalidate (SWR) dual-key caching
- **Circuit breaker** -- per-URL failure tracking with half-open recovery
- **APScheduler** -- periodic background data refresh
- **Rate limiter** -- fixed-window, proxy-aware, with `X-RateLimit-*` headers

## Quick Start

### Docker Compose (recommended)

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env -- set API_KEY, DB_USER, DB_PASSWORD, REDIS_PASSWORD

# 2. Start all services
docker compose up --build

# 3. Verify
curl http://localhost:8000/admin/health
```

### Local Development

```bash
# Requires running PostgreSQL and Redis instances
pip install -r requirements.txt

# Set required environment variables
export API_KEY=your-secret-key
export DB_USER=postgres
export DB_PASSWORD=postgres
export ENVIRONMENT=development

uvicorn app.main:app --reload --port 8000
```

## API Reference

All endpoints except `/admin/health` require the `X-API-Key` header.

### Data Endpoints (`/api/v1`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/aggregate` | Aggregated summary across all sources (cached with SWR) |
| `GET` | `/api/v1/records` | Paginated records. Query params: `source_key`, `page`, `page_size` |
| `GET` | `/api/v1/records/{id}` | Single record by ID |
| `POST` | `/api/v1/refresh` | Fire-and-forget background refresh (returns 202) |
| `POST` | `/api/v1/refresh/sync` | Blocking refresh -- waits for completion |
| `GET` | `/api/v1/logs` | Recent fetch audit logs. Query param: `limit` |

### Admin Endpoints (`/admin`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/health` | No | Health check (DB, Redis, scheduler status) |
| `GET` | `/admin/metrics` | Yes | Cache hit/miss stats and circuit breaker state |
| `DELETE` | `/admin/cache` | Yes | Invalidate all cached aggregates |
| `GET` | `/admin/sources` | Yes | List configured data sources |

### Example Requests

```bash
# Health check
curl http://localhost:8000/admin/health

# Fetch aggregate (requires API key)
curl -H "X-API-Key: your-secret-key" http://localhost:8000/api/v1/aggregate

# Trigger refresh
curl -X POST -H "X-API-Key: your-secret-key" http://localhost:8000/api/v1/refresh

# Paginated records
curl -H "X-API-Key: your-secret-key" \
  "http://localhost:8000/api/v1/records?source_key=posts&page=1&page_size=10"

# Cache metrics
curl -H "X-API-Key: your-secret-key" http://localhost:8000/admin/metrics
```

## Configuration

All configuration is via environment variables (loaded from `.env`). See `.env.example` for the full list.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | Yes | -- | API key for authenticated endpoints |
| `DB_USER` | Yes | -- | PostgreSQL username |
| `DB_PASSWORD` | Yes | -- | PostgreSQL password |
| `DB_HOST` | No | `localhost` | PostgreSQL host |
| `DB_NAME` | No | `aggregator` | PostgreSQL database name |
| `REDIS_PASSWORD` | No | `""` | Redis password |
| `REDIS_HOST` | No | `localhost` | Redis host |
| `ENVIRONMENT` | No | `production` | `development`, `staging`, or `production` |
| `SCHEDULER_ENABLED` | No | `true` | Enable/disable background refresh |
| `REFRESH_INTERVAL_MINUTES` | No | `10` | Background refresh interval |
| `RATE_LIMIT_REQUESTS` | No | `100` | Max requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | No | `60` | Rate limit window duration |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | Allowed CORS origins (JSON array) |

Setting `ENVIRONMENT=development` enables `/docs` (Swagger UI) and `/redoc`.

## Project Structure

```
realtime_aggregator/
  app/
    __init__.py
    main.py              # FastAPI app, lifespan, middleware stack
    config.py            # Pydantic settings from environment
    auth.py              # API key authentication
    database.py          # SQLAlchemy async engine and session
    models.py            # DataRecord, FetchAudit ORM models
    schemas.py           # Pydantic request/response schemas
    cache.py             # Redis SWR caching primitives
    middleware.py         # Rate limiter, logging, security headers
    exceptions.py        # Domain exceptions and error handlers
    routers/
      data.py            # /api/v1 endpoints
      admin.py           # /admin endpoints
    repositories/
      records.py         # DataRecord queries (upsert, paginate)
      audits.py          # FetchAudit queries
    services/
      fetcher.py         # HTTP fetcher with circuit breaker + retry
      aggregator.py      # Aggregation logic with SWR cache
      scheduler.py       # APScheduler background refresh
  tests/
    conftest.py          # Fixtures (SQLite DB, mocked Redis, auth bypass)
    test_cache.py        # Cache key builder tests
    test_fetcher.py      # Circuit breaker tests
    test_routes.py       # API endpoint integration tests
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example
  .env                   # Your local config (git-ignored)
  .gitignore
  .dockerignore
```

## Testing

```bash
# Run all tests (no PostgreSQL or Redis required)
python -m pytest tests/ -v

# Tests use SQLite in-memory and mocked Redis
```

## Security

- API key authentication on all data endpoints (`X-API-Key` header)
- Timing-safe key comparison (`hmac.compare_digest`)
- Security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
- CORS restricted to configured origins
- Rate limiting with `X-RateLimit-*` response headers
- No credentials in source code -- all secrets via environment variables
- PostgreSQL and Redis ports internal-only (not exposed to host)
- Redis requires password authentication
- `.env` excluded from Docker image via `.dockerignore`
- API docs disabled in production
