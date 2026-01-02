"""E2E Demo Application - Flask app factory."""

import asyncio
import atexit
import contextlib

from flask import Flask
from psycopg_pool import AsyncConnectionPool

from .config import Config


def create_app(config_class: type = Config) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize database pool
    _init_database(app)

    # Register blueprints
    from .web.routes import web_bp

    app.register_blueprint(web_bp)

    from .api.routes import api_bp

    app.register_blueprint(api_bp, url_prefix="/api/v1")

    return app


def _init_database(app: Flask) -> None:
    """Initialize the async database connection pool."""
    database_url = app.config.get("DATABASE_URL", Config.DATABASE_URL)

    # Create pool (will be opened on first use)
    pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=2,
        max_size=10,
        open=False,
    )

    # Store pool in app config for access in routes
    app.config["pool"] = pool
    app.config["pool_opened"] = False

    # Register cleanup on app shutdown
    @atexit.register
    def close_pool() -> None:
        if app.config.get("pool_opened"):
            with contextlib.suppress(Exception):
                asyncio.get_event_loop().run_until_complete(pool.close())


def run_async(coro):
    """Helper to run async code in sync Flask context."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
