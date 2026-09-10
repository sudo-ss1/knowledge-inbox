from fastapi import APIRouter, Depends

from ..config import Settings
from ..errors import ApiError
from ..schemas import QueryRequest, QueryResponse, Source
from .deps import get_answerer, get_settings_dep

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    answerer=Depends(get_answerer),
    settings: Settings = Depends(get_settings_dep),
) -> QueryResponse:
    if not settings.openai_api_key:
        raise ApiError(
            "embedder_unavailable",
            "Answering needs embeddings. Set OPENAI_API_KEY and restart.",
            503,
        )

    result = await answerer.answer(
        payload.question, top_k=payload.top_k or settings.retrieval_top_k
    )

    return QueryResponse(
        answer=result.answer,
        sources=[
            Source(
                marker=citation.marker,
                item_id=citation.item_id,
                chunk_id=citation.chunk_id,
                title=citation.title,
                source=citation.source_url,
                snippet=citation.snippet,
                score=citation.score,
            )
            for citation in result.citations
        ],
        abstained=result.abstained,
        timings_ms=result.timings_ms,
    )
