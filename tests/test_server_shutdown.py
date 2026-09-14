import signal
from unittest.mock import patch

import server


class RecordingIOLoop:
    def __init__(self):
        self.scheduled = []

    def add_callback_from_signal(self, callback):
        self.scheduled.append(callback)


class TestSignalHandler:
    """Guards against server.py signal_handler regressing to calling dial
    I/O synchronously from the raw signal handler.

    signal_handler() runs on the main thread and can interrupt the
    PeriodicCallback mid serial-transaction, while SerialHardware.lock
    (a non-reentrant threading.Lock) is held. Calling shut_down_dials()
    directly from there re-enters that same lock on the same thread and
    deadlocks forever - which is what made the server hang on Ctrl+C.
    The fix defers all dial/IOLoop work to IOLoop.add_callback_from_signal
    so it only ever runs as an ordinary, non-reentrant callback.
    """

    def test_signal_handler_does_not_touch_dials_synchronously(self):
        service = object.__new__(server.Dial_API_Service)
        calls = []
        service.shut_down_dials = lambda: calls.append('shut_down_dials')
        service.shutdown_server = lambda: calls.append('shutdown_server')

        fake_loop = RecordingIOLoop()
        with patch.object(server, 'pid_lock'), \
             patch.object(server, 'show_info_msg'), \
             patch.object(server.IOLoop, 'current', return_value=fake_loop):
            service.signal_handler(signal.SIGINT, None)

        assert calls == [], (
            "signal_handler must not run dial shutdown work synchronously; "
            f"it can deadlock on SerialHardware.lock. Ran: {calls}"
        )
        assert len(fake_loop.scheduled) == 1

        # The deferred callback performs the actual shutdown work once it's
        # safe to run as a normal, non-reentrant IOLoop callback.
        fake_loop.scheduled[0]()
        assert calls == ['shut_down_dials', 'shutdown_server']
