import uvicorn
from app.config import HOST, PORT

if __name__ == "__main__":
    print(f"Starting Dazzle by Dua API server at http://{HOST}:{PORT}")
    print(f"Interactive Swagger documentation available at http://{HOST}:{PORT}/docs")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=True)
