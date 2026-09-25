"""ServerDialHandler owns the dial records: built from the bus scan and DB, updated by easing, rename and reload."""
import types

import server_dial_handler
from server_dial_handler import ServerDialHandler, DB_COLUMNS

DB_ROW = {
    'dial_name': 'Desk', 'dial_build_hash': 'h', 'dial_fw_version': 'f',
    'dial_hw_version': 'w', 'dial_protocol_version': 'p',
    'easing_dial_step': 2, 'easing_dial_period': 50,
    'easing_backlight_step': 5, 'easing_backlight_period': 100,
}


class FakeConfig:
    def __init__(self, row_exists=True):
        self.row_exists = row_exists
        self.writes = []

    def dial_fetch_db_info(self, dial_uid):
        return dict(DB_ROW)

    def update_dial_db_cell_with_dict(self, dial_uid, values_dict):
        self.writes.append((dial_uid, values_dict))
        return self.row_exists


class FakeDriver:
    def __init__(self):
        self.calls = []

    def get_dial_list(self, rescan=False):
        return {3: 'AAA'}

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, *args))
            return True
        return record


def _handler(config=None):
    handler = object.__new__(ServerDialHandler)
    handler.dial_driver = FakeDriver()
    handler.server_config = config or FakeConfig()
    handler.dials = {}
    handler.rebuild_dials(handler.dial_driver.get_dial_list(True))
    return handler


def test_reload_builds_record_from_scan_and_db_row(tmp_path, monkeypatch):
    monkeypatch.setattr(server_dial_handler, 'UPLOAD_DIR', str(tmp_path))
    dial = _handler().dials['AAA']

    assert dial['index'] == '3'
    assert dial['dial_name'] == 'Desk'
    assert dial['fw_hash'] == 'h'
    assert dial['easing'] == {'dial_step': 2, 'dial_period': 50,
                              'backlight_step': 5, 'backlight_period': 100}
    assert not (set(DB_ROW) - set(DB_COLUMNS)) & set(dial), "DB column names leaked into the record"
    assert dial['backlight_changed'] is True
    assert dial['value_unresponsive'] is False


def test_easing_send_touches_neither_record_nor_db():
    config = FakeConfig()
    handler = _handler(config)

    sent = handler.dial_send_easing('AAA', 'dial', step=1, period=20)

    assert sent == {'dial_step': 1, 'dial_period': 20}
    assert [c[0] for c in handler.dial_driver.calls] == ['dial_easing_dial_step', 'dial_easing_dial_period']
    assert handler.dials['AAA']['easing']['dial_step'] == 2
    assert config.writes == []


def test_easing_store_records_and_persists():
    config = FakeConfig()
    handler = _handler(config)

    handler.dial_store_easing('AAA', handler.dial_send_easing('AAA', 'backlight', step=7))

    assert handler.dial_driver.calls == [('dial_easing_backlight_step', '3', 7)]
    assert handler.dials['AAA']['easing']['backlight_step'] == 7
    assert handler.dials['AAA']['easing']['backlight_period'] == 100
    assert config.writes == [('AAA', {'easing_backlight_step': 7})]


def test_easing_on_unknown_dial_is_none():
    assert _handler().dial_send_easing('BBB', 'dial', step=1) is None


def test_rename_reaches_the_record_immediately():
    handler = _handler()

    assert handler.dial_set_name('AAA', 'Shelf') is True
    assert handler.get_dial_info('AAA')['dial_name'] == 'Shelf'


def test_rename_without_db_row_fails_and_keeps_name():
    handler = _handler(FakeConfig(row_exists=False))

    assert handler.dial_set_name('AAA', 'Shelf') is False
    assert handler.dials['AAA']['dial_name'] == 'Desk'


def test_reload_from_hardware_writes_one_row():
    config = FakeConfig()
    handler = _handler(config)
    handler.dial_driver = types.SimpleNamespace(
        dial_get_fw_hash=lambda i: 'H2', dial_get_fw_version=lambda i: 'F2',
        dial_get_hw_version=lambda i: 'W2', dial_get_protocol_version=lambda i: 'P2',
        dial_easing_get_config=lambda i: {'dial_step': 9, 'dial_period': 90,
                                          'backlight_step': 8, 'backlight_period': 80},
    )

    info = handler.dial_read_info_from_hardware('AAA')
    assert config.writes == []
    dial = handler.dial_store_info('AAA', info)

    assert dial['fw_version'] == 'F2'
    assert dial['easing']['backlight_period'] == 80
    assert config.writes == [('AAA', {
        'dial_build_hash': 'H2', 'dial_fw_version': 'F2',
        'dial_hw_version': 'W2', 'dial_protocol_version': 'P2',
        'easing_dial_step': 9, 'easing_dial_period': 90,
        'easing_backlight_step': 8, 'easing_backlight_period': 80,
    })]


def test_rename_of_dial_off_the_bus_fails_without_db_write():
    config = FakeConfig()
    handler = _handler(config)

    assert handler.dial_set_name('BBB', 'Shelf') is False
    assert config.writes == []


def test_store_info_for_a_missing_read_or_dial_is_false():
    config = FakeConfig()
    handler = _handler(config)

    assert handler.dial_read_info_from_hardware('BBB') is None
    assert handler.dial_store_info('AAA', None) is False
    assert handler.dial_store_info('BBB', {'fw_version': 'F2'}) is False
    assert config.writes == []


def test_empty_rescan_keeps_the_records():
    handler = _handler()
    dials = handler.dials

    assert handler.rebuild_dials({}) is dials
