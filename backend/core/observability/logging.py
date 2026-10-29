import logging
import os

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("caseplatform")


def get_logger(name=None):
    return logging.getLogger(name or "caseplatform")
