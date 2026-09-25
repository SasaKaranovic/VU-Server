"""A successful bus-wide reset, or a per-dial reset, re-arms each dial's value, backlight and image and clears its backoff latch."""
import types

import pytest


@pytest.fixture
def latched_handler(make_handler):
    """A handler whose dial 'AAA' has everything delivered and its backlight latched unresponsive."""
    handler = make_handler()
    handler.dials['AAA'].update({
        'value_changed': False, 'backlight_changed': False, 'image_changed': False,
        'backlight_fail_count': 3, 'backlight_retry_after': 999999, 'backlight_unresponsive': True,
    })
    return handler


def _assert_rearmed(dial):
    assert dial['value_changed'] is True
    assert dial['backlight_changed'] is True
    assert dial['image_changed'] is True
    assert dial['backlight_unresponsive'] is False
    assert dial['backlight_fail_count'] == 0
    assert dial['backlight_retry_after'] == 0


def test_reset_all_devices_rearms_dials_on_success(latched_handler):
    calls = []
    latched_handler.dial_driver = types.SimpleNamespace(reset_all_devices=lambda: calls.append(1) or True)

    assert latched_handler.reset_all_devices() is True
    assert calls == [1]
    _assert_rearmed(latched_handler.dials['AAA'])


def test_reset_all_devices_leaves_state_untouched_on_failure(latched_handler):
    # The hardware never reset, so the cached latch state is still accurate.
    latched_handler.dial_driver = types.SimpleNamespace(reset_all_devices=lambda: False)

    assert latched_handler.reset_all_devices() is False

    dial = latched_handler.dials['AAA']
    assert dial['backlight_unresponsive'] is True
    assert dial['backlight_fail_count'] == 3
    assert dial['value_changed'] is False


def test_reset_device_rearms_only_the_target_dial(latched_handler):
    latched_handler.dials['BBB'] = dict(latched_handler.dials['AAA'], uid='BBB')

    assert latched_handler.reset_device('AAA') is True

    _assert_rearmed(latched_handler.dials['AAA'])
    other = latched_handler.dials['BBB']
    assert other['backlight_unresponsive'] is True
    assert other['backlight_fail_count'] == 3
    assert other['value_changed'] is False


def test_reset_device_unknown_dial_returns_false(latched_handler):
    assert latched_handler.reset_device('DOESNOTEXIST') is False
