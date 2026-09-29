"""FastAPI application setup, pages, API routers, and static files."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from . import public, admin
from models.database import init_db
from config.settings import settings
from utils.logging_config import configure_app_logging
import os

app = FastAPI(title="Healthcare HR Job Aggregator", version="2.0.0")
configure_app_logging()

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Templates
templates = Jinja2Templates(directory=str(settings.BASE_DIR / "app"))

# Initialize DB tables and seed data on startup
@app.on_event("startup")
def on_startup():
    """Initialize the local database before serving requests."""
    init_db()

# Include API Routers
app.include_router(public.router, prefix="/api")
app.include_router(admin.router, prefix="/api/admin")

# Frontend Routes
@app.get("/")
async def read_root(request: Request):
    """Render the main job offers dashboard."""
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/offers/{offer_id}")
async def read_offer_detail(request: Request, offer_id: int):
    """Render the page shell that loads offer details for the given ID."""
    return templates.TemplateResponse(request=request, name="offer_detail.html", context={"offer_id": offer_id})

@app.get("/matching")
async def read_matching_explanation(request: Request):
    """Render the explanation of the application's match scoring."""
    return templates.TemplateResponse(request=request, name="matching.html")

@app.get("/admin")
async def read_admin(request: Request):
    """Render the local administration dashboard."""
    return templates.TemplateResponse(request=request, name="admin.html")

# Mount static files for Phase 6 Frontend
static_path = settings.BASE_DIR / "app" / "static"
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
