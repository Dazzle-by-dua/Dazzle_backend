"""
ASGI entrypoint for hosting platforms like Render that default to `uvicorn main:app`.
Re-exports the canonical FastAPI application instance from `app.main`.
"""
import os
import uvicorn
from app.main import app

__all__ = ["app"]

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
