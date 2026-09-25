"""An update queued from the IOLoop while the serial worker is mid-send is delivered on the next flush, not lost.

Each driver stub queues a new request from inside the send, where the IOLoop thread can interleave.
"""
import types


def test_backlight_queued_during_send_is_still_delivered(make_handler):
    sent = []

    def send(_index, red, green, blue, white):
        sent.append((red, green, blue, white))
        if len(sent) == 1:
            handler.dial_set_backlight('AAA', 0, 0, 100, 0)
        return True

    handler = make_handler(types.SimpleNamespace(dial_set_backlight=send))

    handler._flush('backlight')
    assert sent == [(100, 0, 0, 0)]
    assert handler.dials['AAA']['backlight_changed'] is True, "colour queued mid-send was dropped"

    handler._flush('backlight')
    assert sent[-1] == (0, 0, 100, 0)
    assert handler.dials['AAA']['backlight_changed'] is False


def test_value_queued_during_send_is_still_delivered(make_handler):
    sent = []

    def send(_index, value):
        sent.append(value)
        if len(sent) == 1:
            handler.dial_set_percent('AAA', 75)
        return True

    handler = make_handler(types.SimpleNamespace(dial_single_set_percent=send))

    handler._flush('value')
    assert sent == [50]
    assert handler.dials['AAA']['value_changed'] is True, "value queued mid-send was dropped"

    handler._flush('value')
    assert sent[-1] == 75
    assert handler.dials['AAA']['value_changed'] is False


def test_same_colour_requeued_during_send_is_considered_delivered(make_handler):
    # The hardware already shows the colour that just went out, so no second write.
    sent = []

    def send(_index, red, green, blue, white):
        sent.append((red, green, blue, white))
        if len(sent) == 1:
            handler.dial_set_backlight('AAA', 100, 0, 0, 0)
        return True

    handler = make_handler(types.SimpleNamespace(dial_set_backlight=send))

    handler._flush('backlight')
    assert handler.dials['AAA']['backlight_changed'] is False
    handler._flush('backlight')
    assert sent == [(100, 0, 0, 0)]
