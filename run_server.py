"""
Quick launcher for the UPSTREAM verification server.
Usage:
    python run_server.py
"""
import uvicorn

if __name__ == "__main__":
    print("Starting UPSTREAM Verification API on http://127.0.0.1:8000 ...")
    print("Interactive API Docs available at http://127.0.0.1:8000/docs")
    uvicorn.run("services.api.main:app", host="127.0.0.1", port=8000, reload=True)

