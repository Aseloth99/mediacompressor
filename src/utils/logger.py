"""Dönen dosya günlüğü — kullanıcı veri dizinine yazar."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from os import makedirs
from os.path import join
from tempfile import gettempdir

from ..core.app_info import APP_ID
from .helpers import get_user_log_dir

_LOGGER: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger(APP_ID)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    log_dir = get_user_log_dir()
    try:
        makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = join(gettempdir(), APP_ID, "logs")
        makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = RotatingFileHandler(
        join(log_dir, f"{APP_ID}.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    _LOGGER = logger
    return logger


def log_info(message: str) -> None:
    get_logger().info(message)


def log_error(message: str, exc: Exception | None = None) -> None:
    if exc is not None:
        get_logger().exception("%s | %s: %s", message, type(exc).__name__, exc)
    else:
        get_logger().error(message)
