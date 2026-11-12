import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# One value per request (per async task). "-" when logging outside a request (startup, scripts).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_default_record_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs) -> logging.LogRecord:
    record = _default_record_factory(*args, **kwargs)
    record.request_id = request_id_var.get()
    return record


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(level: str = "INFO") -> None:
    logging.setLogRecordFactory(_record_factory)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Uvicorn installs its own handlers; route its logs through ours instead.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    # Our middleware logs each request with its id; uvicorn's access log would duplicate it.
    logging.getLogger("uvicorn.access").disabled = True