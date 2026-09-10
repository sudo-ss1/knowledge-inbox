"""HTML to readable text.

trafilatura earns its dependency here: naive tag-stripping leaves navigation
and footer text in the corpus, which then gets embedded and retrieved as
noise. Text quality at ingest is the cheapest lever on answer quality.
"""

import trafilatura

from ..errors import ApiError

MIN_USABLE_CHARS = 50
MAX_TITLE_CHARS = 200


def extract(html: str, url: str) -> tuple[str, str]:
    text = (
        trafilatura.extract(html, include_comments=False, include_tables=True, favor_recall=True)
        or ""
    ).strip()

    if len(text) < MIN_USABLE_CHARS:
        raise ApiError(
            "extraction_empty",
            "Could not find readable text on that page. It may be JavaScript-rendered.",
            422,
        )

    return _title(html, url), text


def _title(html: str, url: str) -> str:
    try:
        metadata = trafilatura.extract_metadata(html)
    except Exception:  # noqa: BLE001 -- trafilatura raises assorted, undocumented parse errors
        metadata = None

    title = getattr(metadata, "title", None)
    return (title or url)[:MAX_TITLE_CHARS]
