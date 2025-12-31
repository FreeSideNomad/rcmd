"""E2E Demo Application - Flask app factory."""

from flask import Flask

from .config import Config


def create_app(config_class: type = Config) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Register blueprints
    from .web.routes import web_bp

    app.register_blueprint(web_bp)

    from .api.routes import api_bp

    app.register_blueprint(api_bp, url_prefix="/api/v1")

    return app
