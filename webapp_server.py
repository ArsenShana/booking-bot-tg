import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Zaman Booking WebApp")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get the directory where this script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEBAPP_DIR = os.path.join(BASE_DIR, "webapp")

# Serve static files from webapp directory
if os.path.isdir(WEBAPP_DIR):
    app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")
else:
    @app.get("/")
    async def root():
        return {"status": "error", "message": f"Webapp directory not found at {WEBAPP_DIR}"}
