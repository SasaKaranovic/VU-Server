"""The log file must land under the user's real home directory.

On macOS the `~` in the log path was never expanded, so a literal `./~` folder
appeared in the working directory. On Linux the path assumed `/home/<user>`.
"""
import logging
import os
import runpy
import sys

import pytest

BASE_LOGGER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'dials', 'base_logger.py')


@pytest.fixture
def run_base_logger(tmp_path, monkeypatch):
    """Execute base_logger.py for a given platform with HOME pointed at tmp_path."""
    home = tmp_path / 'home'
    workdir = tmp_path / 'cwd'
    home.mkdir()
    workdir.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.chdir(workdir)

    root_logger = logging.getLogger('kr_gauge_root')
    saved_handlers = list(root_logger.handlers)

    def _run(platform):
        monkeypatch.setattr(sys, 'platform', platform)
        return runpy.run_path(BASE_LOGGER)['logFile']

    yield home, workdir, _run

    for extra in [h for h in root_logger.handlers if h not in saved_handlers]:
        root_logger.removeHandler(extra)
        extra.close()


@pytest.mark.parametrize('platform', ['darwin', 'linux'])
def test_log_file_is_under_home_directory(run_base_logger, platform):
    home, workdir, run = run_base_logger

    log_file = run(platform)

    assert log_file.startswith(str(home) + os.sep)
    assert not (workdir / '~').exists()
