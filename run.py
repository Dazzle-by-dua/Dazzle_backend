import os
import uvicorn

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    print(f"Starting Dazzle by Dua API server at http://{host}:{port}")
    print(f"Interactive Swagger documentation available at http://{host}:{port}/docs")
    uvicorn.run("main:app", host=host, port=port, reload=False)
