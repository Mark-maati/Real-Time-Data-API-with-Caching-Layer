import structlog
import logging
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.exceptions import HTTPException

from app.config import settings
from app.database import init_db, close_db
from app.cache import init_redis_pool, close_redis_pool
from app.exceptions import AppError, app_error_handler, http_error_handler
from app.middleware import RateLimitMiddleware, LoggingMiddleware, SecurityHeadersMiddleware
from app.routers.data import router as data_router
from app.routers.admin import router as admin_router
from app.services.scheduler import start_scheduler, stop_scheduler

# ── Structured logging setup ──────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.basicConfig(level=logging.INFO)

log = structlog.get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("app.starting", env=settings.ENVIRONMENT, version=settings.APP_VERSION)
    await init_db()
    await init_redis_pool()
    start_scheduler()
    log.info("app.ready")
    yield
    log.info("app.shutting_down")
    stop_scheduler()
    await close_redis_pool()
    await close_db()
    log.info("app.stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
    lifespan=lifespan,
)

# ── Middleware (order matters — outermost first) ───────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# ── Exception handlers ────────────────────────────────────────────────────────
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(data_router)
app.include_router(admin_router)
