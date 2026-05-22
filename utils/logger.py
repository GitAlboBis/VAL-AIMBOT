"""
Minimal logger for the detection framework.
Console-only output, no file logging in production mode.
WARNING level minimum in production per PRD constraints.
"""

import logging
import sys


def setup_logger(name: str = "framework", level: str = "WARNING") -> logging.Logger:
    """
    Setup a console-only logger.

    Args:
        name: Logger name
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    log_level = getattr(logging, level.upper(), logging.WARNING)
    logger.setLevel(log_level)

    # Console-only handler — NO file output (PRD constraint #8)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    # Minimal format — avoid leaking info
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Don't propagate to root logger
    logger.propagate = False

    return logger


__all__ = ['setup_logger']
