"""
Azure AI Document Intelligence — Banking Document Processing Pipeline.
FastAPI application entry point with Web UI and Azure Blob Storage integration.

Author: Jalal Ahmed Khan
Description: End-to-end document extraction pipeline for banking/BFSI using
             Azure AI Document Intelligence, Azure OpenAI GPT-4o, and OpenCV.

Run locally:   uvicorn src.main:app --reload --port 8000
Run on Azure:  Deployed as Azure App Service (see README)
"""

import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .routers import documents, health
from .services.storage import DocumentStorage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Resolve static files directory
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("Starting Banking Document Intelligence Pipeline...")
    storage = DocumentStorage()
    await storage.initialize_tables()
    logger.info(f"Static files: {STATIC_DIR}")
    logger.info("Application ready — accepting requests")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Banking Document Intelligence API",
    description=(
        "End-to-end document extraction pipeline for banking and financial services. "
        "Processes invoices, cheques, KYC forms, ID documents, and trade finance "
        "documents using Azure AI Document Intelligence and Azure OpenAI GPT-4o."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(health.router)
app.include_router(documents.router)

# Serve static files (CSS, JS, images if needed)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_frontend():
    """Serve the web UI — the main user-facing page."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "service": "Banking Document Intelligence API",
        "version": "1.0.0",
        "ui": "Place index.html in /static to enable the web UI",
        "docs": "/docs",
        "health": "/health",
    }
