import sys
from pathlib import Path

# Ensure PartShelf directory is in sys.path regardless of execution working directory
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.api import inventory_api_routes, project_api_routes, web_routes, library_api_routes, search_api_routes, bom_api_routes, warehouse_api_routes, scan_api_routes
from app.services.external_library_service import ensure_libraries_on_startup
from db.database import engine
import app.models
from db.schema_migrations import initialize_main_database

initialize_main_database(engine)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_libraries_on_startup()
    yield

app = FastAPI(lifespan=lifespan)

STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(web_routes.router, tags=["Web Pages"])
app.include_router(inventory_api_routes.router, prefix="/api/inventory")
app.include_router(project_api_routes.router, prefix="/api/projects")
app.include_router(bom_api_routes.router, prefix="/api/projects/bom", tags=["BOM Import"])
app.include_router(library_api_routes.router, prefix="/api/libraries", tags=["External Libraries"])
app.include_router(search_api_routes.router, prefix="/api/search", tags=["Global Search"])
app.include_router(warehouse_api_routes.router, prefix="/api/warehouse", tags=["Warehouse"])
app.include_router(scan_api_routes.router, prefix="/api/scan", tags=["Scan Import"])

if __name__ == "__main__":
    import uvicorn
    print(f"Starting PartShelf server at http://127.0.0.1:8000 ...")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(BASE_DIR))
