'''
    Shared `kr_gauge_root` logger. `configure_logging()` attaches the stderr and rotating file handlers.
'''
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

logger = logging.getLogger('kr_gauge_root')


def _stderr_formatter():
    pieces = [('%(asctime)s.%(msecs)03d', '0;36'),
              ('pid:%(process)d', '1;31'),
              ('%(filename)-22s %(lineno)5d', '0;34'),
              ('%(levelname)-5s', '1;33'),
              ('%(message)s', '0;32')]

    # sys.stderr is None in a --noconsole build.
    if hasattr(sys.stderr, 'isatty') and sys.stderr.isatty():
        fmt = ' '.join(f'\033[{color}m{text}\033[0m' for text, color in pieces)
    else:
        fmt = ' '.join(text for text, _ in pieces)
    return logging.Formatter(fmt, "%b %d %Y %H:%M:%S")


def _log_file_path():
    if sys.platform == "darwin":
        return os.path.expanduser('~/Library/Logs/KaranovicResearch/vudials/server.log')
    return os.path.join(os.path.expanduser('~'), 'KaranovicResearch', 'vudials', 'server.log')


def configure_logging(level='info'):
    '''
        Attach handlers to the shared logger. Call once, at startup.
        @param level: 'debug' for DEBUG; anything else means INFO.
    '''
    log_file = _log_file_path()
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    file_handler = RotatingFileHandler(log_file, maxBytes=1*1024*1024, backupCount=2)
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(funcName)s(%(lineno)d) %(message)s'))

    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setFormatter(_stderr_formatter())

    logger.addHandler(file_handler)
    logger.addHandler(stderr_handler)
    logger.propagate = False
    logger.setLevel(logging.DEBUG if level.lower() == 'debug' else logging.INFO)
    logger.info("Logging level: %s", logging.getLevelName(logger.level))
