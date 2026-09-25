"""A failed value or backlight write stays pending, backs off, and latches unresponsive after DELIVERY_MAX_FAILURES."""
import pytest

from server_dial_handler import ServerDialHandler

MAX_FAILURES = ServerDialHandler.DELIVERY_MAX_FAILURES

# Per kind: the handler setter, a request equal to the fixture's queued state, and a different one.
REQUEST = {
    'value': (lambda h, v: h.dial_set_percent('AAA', v), 50, 75),
    'backlight': (lambda h, c: h.dial_set_backlight('AAA', *c), (100, 0, 0, 0), (0, 50, 0, 0)),
}

pytestmark = pytest.mark.parametrize('kind', ['value', 'backlight'])


class _CountingDriver:
    """Counts value and backlight writes. `results` is one bool, or a list whose last entry repeats."""

    def __init__(self, results):
        self._results = results
        self.calls = 0

    def _write(self, *_args):
        self.calls += 1
        if isinstance(self._results, list):
            return self._results[min(self.calls - 1, len(self._results) - 1)]
        return self._results

    dial_single_set_percent = _write
    dial_set_backlight = _write


def test_failed_send_stays_pending(kind, make_handler, fake_clock):
    handler = make_handler(_CountingDriver(False))

    assert handler._flush(kind) == 0
    assert handler.dials['AAA'][f'{kind}_changed'] is True


def test_successful_send_clears_pending(kind, make_handler, fake_clock):
    handler = make_handler(_CountingDriver(True))

    assert handler._flush(kind) == 1
    assert handler.dials['AAA'][f'{kind}_changed'] is False


def test_backoff_skips_retry_during_cooldown(kind, make_handler, fake_clock):
    driver = _CountingDriver(False)
    handler = make_handler(driver)

    handler._flush(kind)
    d = handler.dials['AAA']
    assert driver.calls == 1
    assert d[f'{kind}_fail_count'] == 1
    assert d[f'{kind}_retry_after'] == 1001.0

    handler._flush(kind)
    assert driver.calls == 1


def test_backoff_retries_after_cooldown_and_doubles(kind, make_handler, fake_clock):
    driver = _CountingDriver(False)
    handler = make_handler(driver)

    handler._flush(kind)
    fake_clock[0] = 1001.0
    handler._flush(kind)

    assert driver.calls == 2
    assert handler.dials['AAA'][f'{kind}_fail_count'] == 2
    assert handler.dials['AAA'][f'{kind}_retry_after'] == 1003.0


def test_marked_unresponsive_after_max_failures(kind, make_handler, fake_clock):
    driver = _CountingDriver(False)
    handler = make_handler(driver)

    for _ in range(MAX_FAILURES):
        fake_clock[0] += 100  # always past the current cooldown
        handler._flush(kind)

    assert driver.calls == MAX_FAILURES
    assert handler.dials['AAA'][f'{kind}_unresponsive'] is True

    fake_clock[0] += 100
    handler._flush(kind)
    assert driver.calls == MAX_FAILURES


def test_success_resets_backoff_state(kind, make_handler, fake_clock):
    handler = make_handler(_CountingDriver([False, False, True]))

    handler._flush(kind)
    fake_clock[0] += 100
    handler._flush(kind)
    fake_clock[0] += 100

    assert handler._flush(kind) == 1
    d = handler.dials['AAA']
    assert d[f'{kind}_changed'] is False
    assert d[f'{kind}_fail_count'] == 0
    assert d[f'{kind}_retry_after'] == 0
    assert d[f'{kind}_unresponsive'] is False


@pytest.mark.parametrize('request_index', [1, 2], ids=['same', 'different'])
def test_request_rearms_unresponsive_dial(kind, request_index, make_handler, fake_clock):
    # The hardware never reached the cached state, so even an identical request must re-arm the write.
    driver = _CountingDriver(False)
    handler = make_handler(driver)
    handler.dials['AAA'].update({f'{kind}_changed': False, f'{kind}_unresponsive': True,
                                 f'{kind}_fail_count': 5, f'{kind}_retry_after': 999999})
    setter = REQUEST[kind][0]

    assert setter(handler, REQUEST[kind][request_index]) is True
    d = handler.dials['AAA']
    assert d[f'{kind}_changed'] is True
    assert d[f'{kind}_unresponsive'] is False
    assert d[f'{kind}_fail_count'] == 0
    assert d[f'{kind}_retry_after'] == 0

    handler._flush(kind)
    assert driver.calls == 1


def test_rearm_dial_clears_backoff_state(kind, make_handler):
    handler = make_handler(_CountingDriver(True))
    d = handler.dials['AAA']
    d.update({f'{kind}_changed': False, f'{kind}_unresponsive': True,
              f'{kind}_fail_count': 5, f'{kind}_retry_after': 999999})

    handler._rearm_dial(d)

    assert d[f'{kind}_changed'] is True
    assert d[f'{kind}_unresponsive'] is False
    assert d[f'{kind}_fail_count'] == 0
    assert d[f'{kind}_retry_after'] == 0
