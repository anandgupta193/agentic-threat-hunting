"""Shared FastAPI dependencies that read app-level singletons created in the lifespan."""

from fastapi import Request

from app.core.clock import Clock
from app.core.config import Settings
from app.db.engine import Database


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_clock(request: Request) -> Clock:
    return request.app.state.clock
