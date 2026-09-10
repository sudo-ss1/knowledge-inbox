from fastapi import Request

from ..config import Settings
from ..store.repository import ChunkRepository, ItemRepository


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_items(request: Request) -> ItemRepository:
    return request.app.state.items


def get_chunks(request: Request) -> ChunkRepository:
    return request.app.state.chunks


def get_queue(request: Request):
    return request.app.state.queue
