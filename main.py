"""
Root ASGI entry point for Dazzle by Dua Fine Jewellery REST API.
Enables ASGI servers (Uvicorn on Render, Heroku, Docker) to load the application via `main:app`.
"""
import os
import uvicorn
from app.main import app

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    print(f"Starting Dazzle by Dua API server on http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=False)
