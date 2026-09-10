import json
import logging
import sys
import time
from contextvars import ContextVar
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """One event per line. Structured fields ride in record.fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        payload.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class EventLogger:
    """Keeps call sites readable: log.info("item_ready", item_id=..., chunks=3)."""

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def info(self, event: str, **fields: Any) -> None:
        self._log.info(event, extra={"fields": fields})

    def warning(self, event: str, **fields: Any) -> None:
        self._log.warning(event, extra={"fields": fields})

    def error(self, event: str, exc_info: bool | BaseException = False, **fields: Any) -> None:
        self._log.error(event, exc_info=exc_info, extra={"fields": fields})


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").handlers = []
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> EventLogger:
    return EventLogger(name)
