"""A failed percent-set stays pending, backs off, and latches unresponsive after BACKLIGHT_MAX_FAILURES."""

import server_dial_handler
from server_dial_handler import ServerDialHandler


class _CountingValueDriver:
    """Records dial_single_set_percent calls; `results` as in test_bugfixes."""

    def __init__(self, results):
        self._results = results
        self.calls = 0

    def dial_single_set_percent(self, *_args, **_kwargs):
        self.calls += 1
        if isinstance(self._results, list):
            idx = min(self.calls - 1, len(self._results) - 1)
            return self._results[idx]
        return self._results


def _handler(driver):
    handler = object.__new__(ServerDialHandler)
    handler.dials = {
        'AAA': {
            'uid': 'AAA',
            'index': '0',
            'value': 50,
            'value_changed': True,
            'value_fail_count': 0,
            'value_retry_after': 0,
            'value_unresponsive': False,
        }
    }
    handler.dial_driver = driver
    return handler


def _fake_clock(monkeypatch, start=1000.0):
    clock = [start]
    monkeypatch.setattr(server_dial_handler, 'time', lambda: clock[0])
    return clock


def test_value_flag_stays_set_when_send_fails(monkeypatch):
    _fake_clock(monkeypatch)
    handler = _handler(_CountingValueDriver(False))

    updated = handler._flush('value')

    assert updated == 0
    assert handler.dials['AAA']['value_changed'] is True


def test_value_flag_clears_when_send_succeeds(monkeypatch):
    _fake_clock(monkeypatch)
    handler = _handler(_CountingValueDriver(True))

    updated = handler._flush('value')

    assert updated == 1
    assert handler.dials['AAA']['value_changed'] is False


def test_value_send_backs_off_after_failure(monkeypatch):
    clock = _fake_clock(monkeypatch)
    driver = _CountingValueDriver(False)
    handler = _handler(driver)

    handler._flush('value')  # fail 1 -> retry in 1s
    handler._flush('value')  # still cooling down
    assert driver.calls == 1

    clock[0] = 1001.0
    handler._flush('value')  # cooldown elapsed
    assert driver.calls == 2


def test_value_marked_unresponsive_after_max_failures(monkeypatch):
    clock = _fake_clock(monkeypatch)
    driver = _CountingValueDriver(False)
    handler = _handler(driver)

    for _ in range(ServerDialHandler.BACKLIGHT_MAX_FAILURES):
        clock[0] += 100  # always past the current cooldown
        handler._flush('value')

    assert driver.calls == ServerDialHandler.BACKLIGHT_MAX_FAILURES
    assert handler.dials['AAA']['value_unresponsive'] is True

    # Once latched, further polls leave the driver alone.
    clock[0] += 100
    handler._flush('value')
    assert driver.calls == ServerDialHandler.BACKLIGHT_MAX_FAILURES


def test_value_success_resets_backoff_state(monkeypatch):
    clock = _fake_clock(monkeypatch)
    handler = _handler(_CountingValueDriver([False, False, True]))

    handler._flush('value')  # fail 1
    clock[0] += 100
    handler._flush('value')  # fail 2
    clock[0] += 100
    updated = handler._flush('value')  # success

    assert updated == 1
    d = handler.dials['AAA']
    assert d['value_changed'] is False
    assert d['value_fail_count'] == 0
    assert d['value_retry_after'] == 0
    assert d['value_unresponsive'] is False


def test_requesting_same_value_rearms_unresponsive_dial(monkeypatch):
    _fake_clock(monkeypatch)
    driver = _CountingValueDriver(False)
    handler = _handler(driver)
    handler.dials['AAA']['value_changed'] = False
    handler.dials['AAA']['value_unresponsive'] = True
    handler.dials['AAA']['value_fail_count'] = 5

    # The hardware never reached 50, so asking for 50 again must re-arm the
    # write rather than being short-circuited as "already at value".
    assert handler.dial_set_percent('AAA', 50) is True
    d = handler.dials['AAA']
    assert d['value_changed'] is True
    assert d['value_unresponsive'] is False
    assert d['value_fail_count'] == 0

    handler._flush('value')
    assert driver.calls == 1


def test_rearm_dial_clears_value_backoff_state():
    handler = _handler(_CountingValueDriver(True))
    handler.dials['AAA'].update({
        'value_changed': False, 'value_unresponsive': True,
        'value_fail_count': 5, 'value_retry_after': 999999,
        'backlight_changed': False, 'image_changed': False,
    })

    handler._rearm_dial(handler.dials['AAA'])

    d = handler.dials['AAA']
    assert d['value_changed'] is True
    assert d['value_unresponsive'] is False
    assert d['value_fail_count'] == 0
    assert d['value_retry_after'] == 0
