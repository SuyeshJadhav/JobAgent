from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import scout, tailor, tracker, profile, settings

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

@app.get("/")
def read_root():
    return {"status": "ok", "message": "JobAgent Backend API is running."}
