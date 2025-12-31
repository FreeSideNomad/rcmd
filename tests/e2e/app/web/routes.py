"""E2E Web routes - serves HTML pages."""

from flask import Blueprint, render_template

web_bp = Blueprint("web", __name__)


@web_bp.route("/")
def dashboard():
    """Dashboard page."""
    return render_template("pages/dashboard.html")


@web_bp.route("/send-command")
def send_command():
    """Send command page."""
    return render_template("pages/send_command.html")


@web_bp.route("/commands")
def commands():
    """Commands browser page."""
    return render_template("pages/commands.html")


@web_bp.route("/tsq")
def troubleshooting_queue():
    """Troubleshooting queue page."""
    return render_template("pages/tsq.html")


@web_bp.route("/audit")
def audit():
    """Audit trail page."""
    return render_template("pages/audit.html")


@web_bp.route("/settings")
def settings():
    """Settings page."""
    return render_template("pages/settings.html")
