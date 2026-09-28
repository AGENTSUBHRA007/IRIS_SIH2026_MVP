"""
IRIS Digital Twin — CLI entry point.
Run: uvicorn app:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import sys
import logging
import uvicorn

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Import the FastAPI app
from backend.api import app

if __name__ == "__main__":
    print("=" * 65)
    print("           IRIS -- Digital Twin for Conveyor Belts        ")
    print("       Intelligent Real-time Inspection System           ")
    print("                    PS26008 MVP                          ")
    print("=" * 65)
    print("  >>> OPEN IN YOUR BROWSER: http://localhost:8000")
    print("  >>> ALTERNATE LINK:       http://127.0.0.1:8000")
    print("  >>> NOTE: Do NOT enter 0.0.0.0 in your browser address bar")
    print("=" * 65)
    
    uvicorn.run(
        "backend.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=[
            "data/*",
            "data/**",
            "data/uploads/*",
            "*.db",
            "*.db-journal",
            "*.mp4",
            "*.avi",
            "*.mkv",
            "__pycache__/*",
            "*.pyc",
            "models/*",
        ],
        log_level="info",
    )

