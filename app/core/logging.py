from pathlib import Path
import logging
import logging.config
import os


def configure_logging():
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    runtime_file = log_dir / "runtime.log"
    admin_file = log_dir / "admin.log"

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": log_level,
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "level": log_level,
                "filename": str(log_file),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf-8",
            },
            "runtime_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "level": log_level,
                "filename": str(runtime_file),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf-8",
            },
            "admin_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "level": log_level,
                "filename": str(admin_file),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf-8",
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console", "file"],
        },
        "loggers": {
            "runtime": {
                "level": log_level,
                "handlers": ["console", "runtime_file"],
                "propagate": False,
            },
            "admin": {
                "level": log_level,
                "handlers": ["console", "admin_file"],
                "propagate": False,
            },
        },
    }

    logging.config.dictConfig(config)
