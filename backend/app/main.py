from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.db import init_db
from app.realtime import hub
from app.routers import admin, auth, donors, hospitals, ws


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    await hub.start(settings.redis_url)
    yield
    await hub.stop()


app = FastAPI(title="Blood Donor-Hospital Matching API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

for r in (auth.router, donors.router, hospitals.router, admin.router, ws.router):
    app.include_router(r)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


if settings.enable_demo_page:
    @app.get("/demo", include_in_schema=False)
    def demo():
        return FileResponse(Path(__file__).parent / "static" / "demo.html")
