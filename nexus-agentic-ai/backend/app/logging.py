import logging
import sys

from app.config import settings


def setup_logging() -> logging.Logger:
    """Configure structured logging for the NEXUS platform."""
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] - %(message)s"
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger("nexus")
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    return logger


logger = setup_logging()
