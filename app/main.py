from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.api import inventory_api_routes, project_api_routes, web_routes, library_api_routes
from app.services.external_library_service import ensure_libraries_on_startup
from db.database import engine, Base
import app.models

Base.metadata.create_all(bind=engine)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_libraries_on_startup()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(web_routes.router, tags=["Web Pages"])
app.include_router(inventory_api_routes.router, prefix="/api/inventory")
app.include_router(project_api_routes.router, prefix="/api/projects")
app.include_router(library_api_routes.router, prefix="/api/libraries", tags=["External Libraries"])