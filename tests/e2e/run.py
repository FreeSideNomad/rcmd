#!/usr/bin/env python3
"""E2E Demo Application Entry Point - FastAPI with Uvicorn."""

import sys
from pathlib import Path

# Add parent directory to path for commandbus import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os

import uvicorn
from app.main import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    reload = os.environ.get("RELOAD", "1") == "1"

    print(f"Starting E2E Demo Application on http://localhost:{port}")
    print("OpenAPI docs available at http://localhost:{port}/docs")
    print("Press Ctrl+C to stop")

    uvicorn.run(
        "run:app",
        host="0.0.0.0",
        port=port,
        reload=reload,
    )
