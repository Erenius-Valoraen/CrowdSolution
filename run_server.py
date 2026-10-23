"""
CrowdSolution API Server Launcher.
Runs the FastAPI server that delivers verification reports to the frontend in JSON.

Usage:
    python run_server.py
"""
import sys
from pathlib import Path

# Add repo root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

if __name__ == "__main__":
    print("==================================================================")
    print("Starting CrowdSolution API Server on http://127.0.0.1:8000")
    print("Interactive Swagger Docs: http://127.0.0.1:8000/docs")
    print("Alternative Redoc:        http://127.0.0.1:8000/redoc")
    print("==================================================================")
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)

