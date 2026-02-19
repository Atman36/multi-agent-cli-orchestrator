import logging
import json
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("job_id", "step_id", "status", "agent", "role"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    # Avoid duplicate handlers if called multiple times
    root = logging.getLogger()
    if root.handlers:
        return

    lvl = getattr(logging, level.upper(), logging.INFO)
    if json_output:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.setLevel(lvl)
        root.addHandler(handler)
    else:
        logging.basicConfig(
            level=lvl,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )

    # Make uvicorn logs consistent if running via python -m gateway.webhook_server
    logging.getLogger("uvicorn").setLevel(lvl)
    logging.getLogger("uvicorn.error").setLevel(lvl)
    logging.getLogger("uvicorn.access").setLevel(lvl)
