"""Regression tests for a batch of bug fixes.

Covered defects:
  #1 Device_Set_Image `force` flag was dead (string arg compared with `is True`).
  #2 DialSerialDriver.dial_set_backlight crashed (KeyError) on an unknown dial.
  #3 dial_multiple_set_percent passed the value into set_dial's UID slot and
     never recorded it in the dial cache.
  #5 DialsDB.api_update_master never committed the master-key row.
"""
import sqlite3
import types

import pytest

import server_dial_handler
from server import BaseHandler
from dial_driver import DialSerialDriver
from database import DialsDB
from server_dial_handler import ServerDialHandler


# -- #1: force flag argument parsing -----------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("true", True),
    ("True", True),
    ("1", True),
    ("yes", True),
    ("on", True),
    (True, True),
    ("false", False),
    ("0", False),
    ("", False),
    ("no", False),
    (False, False),
])
def test_arg_is_true_parses_query_string_values(value, expected):
    # get_argument returns a *string* when the param is present, or the
    # supplied default otherwise. Neither is ever the `True` singleton, so the
    # old `get_force is True` check could never fire.
    assert BaseHandler._arg_is_true(value) is expected


# -- #2: dial_set_backlight on an unknown dial -------------------------------

def _bare_driver():
    """A DialSerialDriver with no serial port, for pure-logic tests."""
    driver = object.__new__(DialSerialDriver)
    driver.dials = {}
    return driver


def test_dial_set_backlight_unknown_dial_returns_false_without_crashing():
    driver = _bare_driver()
    # Previously this resolved to None via _verify_device and then blew up on
    # self.dials[None]['rgbw'] with a KeyError.
    assert driver.dial_set_backlight('DOESNOTEXIST', 1, 2, 3, 4) is False


# -- #3: dial_multiple_set_percent records values in the cache ----------------

def test_dial_multiple_set_percent_caches_values():
    driver = _bare_driver()
    driver.dials = {
        0: {'index': '0', 'uid': 'AAA', 'value': 0},
        1: {'index': '1', 'uid': 'BBB', 'value': 0},
    }
    driver.commands = types.SimpleNamespace(COMM_CMD_SET_DIAL_PERC_MULTIPLE=0)
    driver.data_type = types.SimpleNamespace(COMM_DATA_KEY_VALUE_PAIR=0)
    sent = {}

    def fake_send(*args, **kwargs):  # pragma: no cover - trivial stub
        sent['called'] = True
        return True

    driver._sendCommand = fake_send

    driver.dial_multiple_set_percent([0, 1], [42, 77])

    assert driver.dials[0]['value'] == 42
    assert driver.dials[1]['value'] == 77
    assert sent.get('called') is True


# -- #5: api_update_master commits -------------------------------------------

def test_api_update_master_is_committed(tmp_path):
    db_file = str(tmp_path / "commit_test.db")
    db = DialsDB(database_file=db_file, init_if_missing=True)

    db.api_update_master('MASTERKEY123')

    # A brand new connection only sees committed rows.
    verify = sqlite3.connect(db_file)
    verify.row_factory = sqlite3.Row
    row = verify.execute(
        "SELECT key_uid FROM api_keys WHERE key_name='MASTER_KEY'"
    ).fetchone()
    verify.close()

    assert row is not None
    assert row['key_uid'] == 'MASTERKEY123'


# -- #6: provision_dials returns the refreshed dial list ----------------------

def test_provision_dials_returns_dial_info(monkeypatch):
    # The /dial/provision endpoint sends back whatever provision_dials()
    # returns. Previously the method returned None, so the endpoint always
    # responded with `data: null`.
    handler = object.__new__(ServerDialHandler)
    handler.dials = {'AAA': {'uid': 'AAA', 'value': 0}}
    handler.dial_driver = types.SimpleNamespace(provision_dials=lambda: True)

    # Keep the test fast and hardware-free.
    monkeypatch.setattr(server_dial_handler, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(handler, '_reload_dials', lambda rescan=False: None)

    result = handler.provision_dials(num_attempts=1)

    assert result == {'AAA': {'uid': 'AAA', 'value': 0}}


# -- #7: get_dial_list drops dials that went offline on rescan ----------------

def test_get_dial_list_rescan_drops_offline_dials():
    driver = _bare_driver()
    # Two dials cached from a previous scan.
    driver.dials = {
        0: {'index': '0', 'uid': 'AAA', 'value': 50},
        1: {'index': '1', 'uid': 'BBB', 'value': 75},
    }
    driver.commands = types.SimpleNamespace(
        COMM_CMD_RESCAN_BUS=0,
        COMM_CMD_GET_DEVICES_MAP=1,
    )
    driver.data_type = types.SimpleNamespace(COMM_DATA_NONE=0)

    # Only index 0 reports online now ("01" = single byte, value 1).
    driver.bus_rescan = lambda: True
    driver._sendCommand = lambda *a, **k: "01"
    driver.dial_get_uid = lambda index: 'AAA'

    result = driver.get_dial_list(rescan=True)

    uids = {dial['uid'] for dial in result}
    assert uids == {'AAA'}          # BBB dropped off the bus
    assert 1 not in driver.dials    # and is gone from the cache


# -- #8: a failed backlight write must not be marked as delivered -------------

def _periodic_handler(backlight_send_result):
    """A bare ServerDialHandler wired to a stub driver for the periodic loop."""
    handler = object.__new__(ServerDialHandler)
    handler.communication_timeout = 5
    handler.dials = {
        'AAA': {
            'uid': 'AAA',
            'index': '0',
            'backlight': {'red': 100, 'green': 0, 'blue': 0, 'white': 0},
            'backlight_changed': True,
            'update_deadline': 0,
        }
    }
    handler.dial_driver = types.SimpleNamespace(
        dial_set_backlight=lambda *a, **k: backlight_send_result
    )
    return handler


def test_backlight_flag_stays_set_when_send_fails():
    # The driver reports the write failed (e.g. dial offline/busy). The change
    # must remain pending so the next poll retries it, otherwise the cached
    # RGBW state silently diverges from the hardware.
    handler = _periodic_handler(backlight_send_result=False)
    updated = handler._periodic_update_dial_backlight()
    assert updated == 0
    assert handler.dials['AAA']['backlight_changed'] is True


def test_backlight_flag_clears_when_send_succeeds():
    handler = _periodic_handler(backlight_send_result=True)
    updated = handler._periodic_update_dial_backlight()
    assert updated == 1
    assert handler.dials['AAA']['backlight_changed'] is False


# -- #15b: backlight retry-backoff + unresponsive cap -------------------------

class _CountingBacklightDriver:
    """Stub driver that records how many times dial_set_backlight was called.

    `results` is either a single bool (returned every call) or a list of bools
    consumed per call (the last entry repeats once exhausted).
    """

    def __init__(self, results):
        self._results = results
        self.calls = 0

    def dial_set_backlight(self, *_args, **_kwargs):
        self.calls += 1
        if isinstance(self._results, list):
            idx = min(self.calls - 1, len(self._results) - 1)
            return self._results[idx]
        return self._results


def _backoff_handler(driver):
    handler = object.__new__(ServerDialHandler)
    handler.communication_timeout = 5
    handler.dials = {
        'AAA': {
            'uid': 'AAA',
            'index': '0',
            'backlight': {'red': 100, 'green': 0, 'blue': 0, 'white': 0},
            'backlight_changed': True,
            'update_deadline': 0,
            'backlight_fail_count': 0,
            'backlight_retry_after': 0,
            'backlight_unresponsive': False,
        }
    }
    handler.dial_driver = driver
    return handler


def _fake_clock(monkeypatch, start=1000.0):
    clock = [start]
    monkeypatch.setattr(server_dial_handler, 'time', lambda: clock[0])
    return clock


def test_backlight_backoff_skips_retry_during_cooldown(monkeypatch):
    _fake_clock(monkeypatch)
    driver = _CountingBacklightDriver(False)
    handler = _backoff_handler(driver)

    handler._periodic_update_dial_backlight()  # attempt 1 -> fail, backoff 1s
    assert driver.calls == 1
    assert handler.dials['AAA']['backlight_fail_count'] == 1
    assert handler.dials['AAA']['backlight_retry_after'] == 1001.0
    assert handler.dials['AAA']['backlight_changed'] is True

    # No time has passed: still cooling down, driver must not be called again.
    handler._periodic_update_dial_backlight()
    assert driver.calls == 1


def test_backlight_backoff_retries_after_cooldown(monkeypatch):
    clock = _fake_clock(monkeypatch)
    driver = _CountingBacklightDriver(False)
    handler = _backoff_handler(driver)

    handler._periodic_update_dial_backlight()  # fail1 -> retry_after = 1001
    assert driver.calls == 1

    clock[0] = 1001.0  # cooldown elapsed
    handler._periodic_update_dial_backlight()  # fail2 -> backoff doubles
    assert driver.calls == 2
    assert handler.dials['AAA']['backlight_fail_count'] == 2
    assert handler.dials['AAA']['backlight_retry_after'] == 1003.0  # +2s


def test_backlight_marked_unresponsive_after_max_failures(monkeypatch):
    clock = _fake_clock(monkeypatch)
    driver = _CountingBacklightDriver(False)
    handler = _backoff_handler(driver)

    for _ in range(ServerDialHandler.BACKLIGHT_MAX_FAILURES):
        clock[0] += 100  # always past the current cooldown
        handler._periodic_update_dial_backlight()

    assert driver.calls == ServerDialHandler.BACKLIGHT_MAX_FAILURES
    assert handler.dials['AAA']['backlight_unresponsive'] is True

    # Once unresponsive, further polls (even past cooldown) stop the driver.
    clock[0] += 100
    handler._periodic_update_dial_backlight()
    assert driver.calls == ServerDialHandler.BACKLIGHT_MAX_FAILURES


def test_backlight_success_resets_backoff_state(monkeypatch):
    clock = _fake_clock(monkeypatch)
    driver = _CountingBacklightDriver([False, False, True])
    handler = _backoff_handler(driver)

    handler._periodic_update_dial_backlight()  # fail1
    clock[0] += 100
    handler._periodic_update_dial_backlight()  # fail2
    clock[0] += 100
    updated = handler._periodic_update_dial_backlight()  # success

    assert updated == 1
    d = handler.dials['AAA']
    assert d['backlight_changed'] is False
    assert d['backlight_fail_count'] == 0
    assert d['backlight_retry_after'] == 0
    assert d['backlight_unresponsive'] is False


def test_requeueing_backlight_rearms_unresponsive_dial(monkeypatch):
    _fake_clock(monkeypatch)
    driver = _CountingBacklightDriver(False)
    handler = _backoff_handler(driver)
    handler.dials['AAA']['backlight_unresponsive'] = True
    handler.dials['AAA']['backlight_fail_count'] = 5
    handler.dials['AAA']['backlight_changed'] = False

    # Queue a NEW colour: must clear the given-up state and re-arm.
    assert handler.dial_set_backlight('AAA', 0, 50, 0, 0) is True
    d = handler.dials['AAA']
    assert d['backlight_unresponsive'] is False
    assert d['backlight_fail_count'] == 0
    assert d['backlight_retry_after'] == 0
    assert d['backlight_changed'] is True

    # And the next poll actually talks to the driver again.
    handler._periodic_update_dial_backlight()
    assert driver.calls == 1


def test_backlight_same_value_not_shortcircuited_while_unresponsive(monkeypatch):
    _fake_clock(monkeypatch)
    driver = _CountingBacklightDriver(False)
    handler = _backoff_handler(driver)
    handler.dials['AAA']['backlight'] = {'red': 10, 'green': 20, 'blue': 30, 'white': 40}
    handler.dials['AAA']['backlight_unresponsive'] = True
    handler.dials['AAA']['backlight_changed'] = False

    # Re-requesting the SAME colour must re-arm, not silently short-circuit.
    handler.dial_set_backlight('AAA', 10, 20, 30, 40)
    d = handler.dials['AAA']
    assert d['backlight_changed'] is True
    assert d['backlight_unresponsive'] is False


def test_dial_set_backlight_uses_bounded_read_timeout():
    # A backlight write should wait a short time for the hub ACK, not the 5s
    # default that freezes the IOLoop when a dial goes silent.
    driver = object.__new__(DialSerialDriver)
    driver.dials = {0: {'index': '0', 'uid': 'AAA', 'rgbw': [0, 0, 0, 0]}}
    driver.commands = types.SimpleNamespace(COMM_CMD_SET_RGB_BACKLIGHT=0x13)
    driver.data_type = types.SimpleNamespace(COMM_DATA_MULTIPLE_VALUE=0x03)
    captured = {}

    def fake_txn(payload, ignore_response=False, read_timeout=None):
        captured['read_timeout'] = read_timeout
        return []  # simulate no response

    driver.serial_transaction = fake_txn

    driver.dial_set_backlight(0, 1, 2, 3, 4)

    assert captured['read_timeout'] == DialSerialDriver.BACKLIGHT_READ_TIMEOUT
    assert captured['read_timeout'] is not None
    assert captured['read_timeout'] < 5


# -- Cleanup: per-instance dial/key state must not be shared class attributes -

@pytest.mark.parametrize("cls,attrs", [
    (DialSerialDriver, ('dials', 'hub_info')),
    (ServerDialHandler, ('dials', 'hub_info')),
])
def test_mutable_state_is_not_a_class_attribute(cls, attrs):
    # These were declared as class-level `{}` dicts, so every instance shared
    # (and mutated) the same object. They must live on the instance instead.
    for attr in attrs:
        assert attr not in vars(cls), (
            f"{cls.__name__}.{attr} is a shared class attribute; "
            "initialise it in __init__ instead."
        )


def test_serverconfig_mutable_state_is_not_a_class_attribute():
    # Imported lazily so the test module doesn't require a config/database.
    from server_config import ServerConfig
    for attr in ('dials', 'api_keys'):
        assert attr not in vars(ServerConfig)
