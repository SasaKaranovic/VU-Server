"""An update queued while the worker is on the bus must not be lost.

Request handlers run on the Tornado IOLoop thread and queue changes by
setting `dial['backlight']` / `dial['value']` plus a `*_changed` flag. The
periodic updater runs on the serial worker thread: it sends the cached value
and then unconditionally cleared the flag. If a new request landed between
the send and the clear, the flag was wiped while the cache already held the
*new* value -- so it was never sent, and because the "already at value"
short-circuit compares against that cache, re-requesting the same value was
dropped too. The dial stayed on the old colour/value until something
different was asked for.

These tests simulate the IOLoop thread queueing a new value from inside the
driver call, i.e. exactly while the worker is mid-send.
"""
import types

from server_dial_handler import ServerDialHandler


def _handler(driver):
    handler = object.__new__(ServerDialHandler)
    handler.communication_timeout = 5
    handler.dials = {
        'AAA': {
            'uid': 'AAA',
            'index': '0',
            'value': 50,
            'value_changed': True,
            'backlight': {'red': 100, 'green': 0, 'blue': 0, 'white': 0},
            'backlight_changed': True,
            'backlight_fail_count': 0,
            'backlight_retry_after': 0,
            'backlight_unresponsive': False,
            'update_deadline': 0,
        }
    }
    handler.dial_driver = driver
    return handler


def test_backlight_queued_during_send_is_still_delivered():
    sent = []
    box = {}

    def send(_index, red, green, blue, white):
        sent.append((red, green, blue, white))
        if len(sent) == 1:
            # IOLoop thread: a new colour arrives while the worker is on the bus.
            box['handler'].dial_set_backlight('AAA', 0, 0, 100, 0)
        return True

    handler = _handler(types.SimpleNamespace(dial_set_backlight=send))
    box['handler'] = handler

    handler._periodic_update_dial_backlight()
    assert sent == [(100, 0, 0, 0)]
    assert handler.dials['AAA']['backlight_changed'] is True, (
        "blue was queued mid-send and its pending flag was wiped")

    # The next poll must deliver the colour that was queued mid-send.
    handler._periodic_update_dial_backlight()
    assert sent[-1] == (0, 0, 100, 0)
    assert handler.dials['AAA']['backlight_changed'] is False


def test_value_queued_during_send_is_still_delivered():
    sent = []
    box = {}

    def send(_index, value):
        sent.append(value)
        if len(sent) == 1:
            # IOLoop thread: a new value arrives while the worker is on the bus.
            box['handler'].dial_set_percent('AAA', 75)
        return True

    handler = _handler(types.SimpleNamespace(dial_single_set_percent=send))
    box['handler'] = handler

    handler._periodic_update_dial_values()
    assert sent == [50]
    assert handler.dials['AAA']['value_changed'] is True, (
        "75 was queued mid-send and its pending flag was wiped")

    handler._periodic_update_dial_values()
    assert sent[-1] == 75
    assert handler.dials['AAA']['value_changed'] is False


def test_same_colour_requeued_during_send_is_considered_delivered():
    # If the value queued mid-send is identical to what just went out, the
    # hardware is already there: no second write, flag cleared.
    sent = []
    box = {}

    def send(_index, red, green, blue, white):
        sent.append((red, green, blue, white))
        if len(sent) == 1:
            box['handler'].dial_set_backlight('AAA', 100, 0, 0, 0)
        return True

    handler = _handler(types.SimpleNamespace(dial_set_backlight=send))
    box['handler'] = handler

    handler._periodic_update_dial_backlight()
    assert handler.dials['AAA']['backlight_changed'] is False
    handler._periodic_update_dial_backlight()
    assert sent == [(100, 0, 0, 0)]
