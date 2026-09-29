"""Bedrock Playground API."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import router
from app.static import mount_frontend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

settings = get_settings()

app = FastAPI(
    title="Bedrock Playground API",
    description="Lightweight API for experimenting with AWS Bedrock models.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router)

if mount_frontend(app):
    logging.getLogger(__name__).info("Serving UI from frontend/dist")
