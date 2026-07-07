"""
JARVIS TRADER Lifespan Helpers
===============================
Utility functions for lifespan management (logging setup, etc.)
"""

import json
import logging
import logging.handlers
import os
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Custom JSON-structured log formatter"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "module": record.module,
            "funcName": record.funcName,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure structured logging with file rotation and console output.
    Called during lifespan startup BEFORE any other module initialization.
    """
    os.makedirs("logs", exist_ok=True)

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.handlers.clear()

    json_formatter = JSONFormatter()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root_logger.addHandler(console_handler)

    file_handler = logging.handlers.RotatingFileHandler(
        filename="logs/jarvis.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(json_formatter)
    root_logger.addHandler(file_handler)
