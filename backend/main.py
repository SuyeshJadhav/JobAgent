from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from backend.routers import scout, tailor, tracker, profile, settings, apply, tracking, sniper

app = FastAPI(title="JobAgent Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scout.router)
app.include_router(tailor.router)
app.include_router(tracker.router)
app.include_router(profile.router)
app.include_router(settings.router)
app.include_router(apply.router, prefix="/api/apply", tags=["Apply"])
app.include_router(tracking.router)
app.include_router(sniper.router)

# Serve the frontend dashboard
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(frontend_dir), html=True), name="dashboard")

@app.get("/")
def read_root():
    return {"status": "ok", "message": "JobAgent Backend API is running."}
