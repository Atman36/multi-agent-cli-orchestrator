import logging
import os


def setup_logging(level: str = "INFO") -> None:
    # Avoid duplicate handlers if called multiple times
    root = logging.getLogger()
    if root.handlers:
        return

    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Make uvicorn logs consistent if running via python -m gateway.webhook_server
    logging.getLogger("uvicorn").setLevel(lvl)
    logging.getLogger("uvicorn.error").setLevel(lvl)
    logging.getLogger("uvicorn.access").setLevel(lvl)
