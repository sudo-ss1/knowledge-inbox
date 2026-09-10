from typing import Literal

from fastapi import APIRouter, Body, Depends, Query

from ..config import Settings
from ..errors import ApiError
from ..logging import get_logger
from ..schemas import (
    IngestAccepted,
    IngestRequest,
    ItemDetail,
    ItemsPage,
    NoteIngest,
    note_title,
    to_detail,
    to_summary,
)
from ..store.repository import ItemRepository
from .deps import get_items, get_queue, get_settings_dep

log = get_logger(__name__)
router = APIRouter(tags=["items"])


@router.post("/ingest", status_code=202, response_model=IngestAccepted)
async def ingest(
    payload: IngestRequest = Body(...),
    items: ItemRepository = Depends(get_items),
    queue=Depends(get_queue),
    settings: Settings = Depends(get_settings_dep),
) -> IngestAccepted:
    if not settings.openai_api_key:
        raise ApiError(
            "embedder_unavailable",
            "Ingestion needs embeddings. Set OPENAI_API_KEY and restart.",
            503,
        )

    if isinstance(payload, NoteIngest):
        item = await items.create(
            type="note",
            source_url=None,
            title=note_title(payload.content),
            raw_content=payload.content,
        )
    else:
        item = await items.create(
            type="url", source_url=str(payload.url), title=None, raw_content=None
        )

    await queue.submit(item.id)
    log.info("ingest_accepted", item_id=item.id, type=item.type)
    return IngestAccepted(
        id=item.id, type=item.type, status=item.status, created_at=item.created_at
    )


@router.get("/items", response_model=ItemsPage)
async def list_items(
    status: Literal["pending", "ready", "failed"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    items: ItemRepository = Depends(get_items),
) -> ItemsPage:
    page, next_cursor = await items.list_page(status=status, limit=limit, cursor=cursor)
    return ItemsPage(items=[to_summary(item) for item in page], next_cursor=next_cursor)


@router.get("/items/{item_id}", response_model=ItemDetail)
async def get_item(item_id: str, items: ItemRepository = Depends(get_items)) -> ItemDetail:
    item = await items.get(item_id)
    if item is None:
        raise ApiError("item_not_found", f"No item with id '{item_id}'.", 404)
    return to_detail(item)
