"""Operator notifications: always logged, and also shown as a message box on Windows."""
import sys
from dials.base_logger import logger

_MESSAGE_BOX_ICONS = {'error': 16, 'warning': 48, 'info': 64}


def notify(level, title, message):
    """Log `message` and, on Windows, show it in a blocking message box.

    @param level: 'error', 'warning' or 'info'.
    """
    getattr(logger, level)(f"{title}: {' '.join(message.split())}")
    if sys.platform == 'win32':
        import ctypes  # pylint: disable=import-outside-toplevel
        ctypes.windll.user32.MessageBoxW(0, message, f"VU Server - {title}", _MESSAGE_BOX_ICONS[level])
