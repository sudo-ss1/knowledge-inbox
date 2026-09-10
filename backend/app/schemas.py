from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from .store.repository import Item

PREVIEW_CHARS = 240
NOTE_TITLE_CHARS = 120


class NoteIngest(BaseModel):
    type: Literal["note"]
    content: Annotated[str, Field(min_length=1, max_length=100_000)]

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content cannot be blank")
        return stripped


class UrlIngest(BaseModel):
    type: Literal["url"]
    url: HttpUrl


IngestRequest = Annotated[NoteIngest | UrlIngest, Field(discriminator="type")]


class IngestAccepted(BaseModel):
    id: str
    type: str
    status: str
    created_at: str


class ItemSummary(BaseModel):
    id: str
    type: str
    title: str | None
    source: str | None
    status: str
    error: str | None
    chunk_count: int
    preview: str
    created_at: str


class ItemDetail(ItemSummary):
    raw_content: str | None


class ItemsPage(BaseModel):
    items: list[ItemSummary]
    next_cursor: str | None


def note_title(content: str) -> str:
    first_line = content.strip().splitlines()[0].strip()
    return first_line[:NOTE_TITLE_CHARS]


def to_summary(item: Item) -> ItemSummary:
    return ItemSummary(
        id=item.id,
        type=item.type,
        title=item.title,
        source=item.source_url,
        status=item.status,
        error=item.error,
        chunk_count=item.chunk_count,
        preview=(item.raw_content or "")[:PREVIEW_CHARS],
        created_at=item.created_at,
    )


def to_detail(item: Item) -> ItemDetail:
    return ItemDetail(**to_summary(item).model_dump(), raw_content=item.raw_content)
