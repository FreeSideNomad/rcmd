"""E2E Web routes - serves HTML pages with Jinja2 templates."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

web_router = APIRouter()

# Setup Jinja2 templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@web_router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Dashboard page."""
    return templates.TemplateResponse(request, "pages/dashboard.html")


@web_router.get("/send-command", response_class=HTMLResponse)
async def send_command(request: Request) -> HTMLResponse:
    """Send command page."""
    return templates.TemplateResponse(request, "pages/send_command.html")


@web_router.get("/commands", response_class=HTMLResponse)
async def commands(request: Request) -> HTMLResponse:
    """Commands browser page."""
    return templates.TemplateResponse(request, "pages/commands.html")


@web_router.get("/tsq", response_class=HTMLResponse)
async def troubleshooting_queue(request: Request) -> HTMLResponse:
    """Troubleshooting queue page."""
    return templates.TemplateResponse(request, "pages/tsq.html")


@web_router.get("/audit", response_class=HTMLResponse)
async def audit(request: Request) -> HTMLResponse:
    """Audit trail page."""
    return templates.TemplateResponse(request, "pages/audit.html")


@web_router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request) -> HTMLResponse:
    """Settings page."""
    return templates.TemplateResponse(request, "pages/settings.html")


@web_router.get("/batches", response_class=HTMLResponse)
async def batches(request: Request) -> HTMLResponse:
    """Batches list page."""
    return templates.TemplateResponse(request, "pages/batches.html")


@web_router.get("/batches/new", response_class=HTMLResponse)
async def batch_new(request: Request) -> HTMLResponse:
    """Create batch page."""
    return templates.TemplateResponse(request, "pages/batch_new.html")


@web_router.get("/batches/{batch_id}", response_class=HTMLResponse)
async def batch_detail(request: Request, batch_id: str) -> HTMLResponse:
    """Batch detail page."""
    return templates.TemplateResponse(request, "pages/batch_detail.html", {"batch_id": batch_id})
