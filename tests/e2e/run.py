#!/usr/bin/env python3
"""E2E Demo Application Entry Point."""

import sys
from pathlib import Path

# Add parent directory to path for commandbus import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"

    print(f"Starting E2E Demo Application on http://localhost:{port}")
    print("Press Ctrl+C to stop")

    app.run(host="0.0.0.0", port=port, debug=debug)
