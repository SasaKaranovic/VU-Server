"""Tests for the bus-wide `reset all devices` action.

The `/api/v0/dial/reset_all` endpoint asks the hub to reset every dial on the
bus. Because a reset reboots each dial to its power-on defaults, the handler
must also clear its cached "already delivered" / unresponsive backlight state so
the periodic loop re-pushes each dial's configured value, colour and image.
"""
import types

from server_dial_handler import ServerDialHandler


def _handler_with_dials():
    handler = object.__new__(ServerDialHandler)
    handler.dials = {
        'AAA': {
            'uid': 'AAA', 'value': 50, 'value_changed': False,
            'backlight_changed': False, 'backlight_fail_count': 3,
            'backlight_retry_after': 999999, 'backlight_unresponsive': True,
            'image_changed': False,
        },
    }
    return handler


def test_reset_all_devices_rearms_dials_on_success():
    handler = _handler_with_dials()
    calls = {'n': 0}

    def fake_reset():
        calls['n'] += 1
        return True

    handler.dial_driver = types.SimpleNamespace(reset_all_devices=fake_reset)

    assert handler.reset_all_devices() is True
    assert calls['n'] == 1

    dial = handler.dials['AAA']
    # Re-armed so the periodic loop re-pushes everything to the rebooted dial.
    assert dial['value_changed'] is True
    assert dial['backlight_changed'] is True
    assert dial['image_changed'] is True
    # The stale unresponsive/backoff latch must be cleared.
    assert dial['backlight_unresponsive'] is False
    assert dial['backlight_fail_count'] == 0
    assert dial['backlight_retry_after'] == 0


def test_reset_all_devices_leaves_state_untouched_on_failure():
    handler = _handler_with_dials()
    handler.dial_driver = types.SimpleNamespace(reset_all_devices=lambda: False)

    assert handler.reset_all_devices() is False

    # A failed hub reset did nothing to the hardware, so the cached latch state
    # must be preserved rather than falsely cleared.
    dial = handler.dials['AAA']
    assert dial['backlight_unresponsive'] is True
    assert dial['backlight_fail_count'] == 3
    assert dial['value_changed'] is False


# -- per-dial software reset --------------------------------------------------

def test_reset_device_rearms_only_the_target_dial():
    handler = _handler_with_dials()
    handler.dials['BBB'] = {
        'uid': 'BBB', 'value': 10, 'value_changed': False,
        'backlight_changed': False, 'backlight_fail_count': 2,
        'backlight_retry_after': 42, 'backlight_unresponsive': True,
        'image_changed': False,
    }

    assert handler.reset_device('AAA') is True

    target = handler.dials['AAA']
    assert target['value_changed'] is True
    assert target['backlight_changed'] is True
    assert target['image_changed'] is True
    assert target['backlight_unresponsive'] is False
    assert target['backlight_fail_count'] == 0
    assert target['backlight_retry_after'] == 0

    # The other dial must be left completely alone.
    other = handler.dials['BBB']
    assert other['backlight_unresponsive'] is True
    assert other['backlight_fail_count'] == 2
    assert other['value_changed'] is False


def test_reset_device_unknown_dial_returns_false():
    handler = _handler_with_dials()
    assert handler.reset_device('DOESNOTEXIST') is False
