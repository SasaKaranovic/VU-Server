import os
from time import time, sleep
from math import trunc
from dials.base_logger import logger

# Where Device_Set_Image stores per-dial images (`img_<uid>`) and where the
# shipped fallback `img_blank` lives.
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'upload')


def dial_image_path(dial_uid):
    """@returns the absolute path of the dial's uploaded image, which may not exist."""
    return os.path.join(UPLOAD_DIR, f'img_{dial_uid}')


def dial_image_file(dial_uid):
    """@returns the dial's uploaded image, or `img_blank` if none was uploaded."""
    # Absolute, because a reset hands it to the driver, which must not resolve it against the CWD.
    path = dial_image_path(dial_uid)
    return path if os.path.exists(path) else os.path.join(UPLOAD_DIR, 'img_blank')


# Dial record field -> `dials` table column. Easing fields live under
# record['easing'] and map to `easing_<field>`.
DB_COLUMNS = {
    'dial_name': 'dial_name',
    'fw_hash': 'dial_build_hash',
    'fw_version': 'dial_fw_version',
    'hw_version': 'dial_hw_version',
    'protocol_version': 'dial_protocol_version',
}
EASING_FIELDS = ('dial_step', 'dial_period', 'backlight_step', 'backlight_period')


def apply_db_row(dial, row):
    """Copy a `dials` table row's stored info and easing into a dial record."""
    for field, column in DB_COLUMNS.items():
        dial[field] = row[column]
    dial['easing'] = {field: row[f'easing_{field}'] for field in EASING_FIELDS}


class ServerDialHandler:
    """Owns the per-dial records, keyed by UID, and queues API updates for the periodic flush.

    The database and the record set are touched only on the IOLoop thread;
    work on the serial worker changes only per-dial delivery state. Methods
    that read the bus return what they read for an IOLoop-side method to store.
    """
    # Retry-backoff for value and backlight writes. A dial that stops ACKing is
    # retried with exponential backoff; after BACKLIGHT_MAX_FAILURES consecutive
    # failures it is marked unresponsive and left alone until it re-appears on a
    # bus rescan or a new value/colour is requested. This keeps one dead dial
    # from spamming the log and blocking the serial bus on every periodic tick.
    BACKLIGHT_MAX_FAILURES = 5
    BACKLIGHT_BACKOFF_BASE = 1.0   # seconds
    BACKLIGHT_BACKOFF_MAX = 30.0   # seconds

    def __init__(self, dial_driver, server_config):
        self.dial_driver = dial_driver
        self.server_config = server_config
        self.dials = {}

        logger.debug("Retrieving list of dials")
        self.rebuild_dials(self.dial_driver.get_dial_list(True))

        logger.debug("Reconfiguring dials with stored behaviour")
        self._send_db_config_to_dials()

        logger.debug("Setting all dials percentage to 0")
        self.dial_driver.set_all_dials_to(0)

        logger.debug("Server dial handler up and running.")

    def periodic_dial_update(self):
        self._flush('value')
        self._flush('backlight')
        self._periodic_update_dial_images()

    def _convert_to_int(self, value):
        try:
            if not isinstance(value, int):
                value = trunc(int(float(value)))
        except Exception as e:
            logger.error(e)
            logger.error(f"Failed to convert value `{value}` to int. Defaulting to 0")
            value = 0

        return value

    def _get_dial(self, dial_uid):
        """@returns the dial record, or None (logged) if the dial is not on the bus."""
        dial = self.dials.get(dial_uid)
        if dial is None:
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
        return dial

    def rebuild_dials(self, dials):
        """Replace the records with one per scanned dial, filled from the database.

        @param dials {bus index: UID} from a bus scan; empty keeps the current records
        @returns the records
        """
        if not dials:
            logger.error("No dials connected to the bus!")
            return self.dials

        # Rebuild from the current bus scan so unplugged dials leave the API's dial list.
        refreshed = {}
        for index, uid in dials.items():
            dial = {
                'uid': uid,
                'index': str(index),
                'value': 0,
                'backlight': {'red': 0, 'green': 0, 'blue': 0, 'white': 0},
                'image_file': dial_image_file(uid),
                'value_changed': False,
                'backlight_changed': True,
                'image_changed': False,
            }
            apply_db_row(dial, self.server_config.dial_fetch_db_info(uid))
            self._clear_delivery_state(dial, 'value')
            self._clear_delivery_state(dial, 'backlight')
            refreshed[uid] = dial
        self.dials = refreshed
        return self.dials

    def _send_db_config_to_dials(self):
        for uid, dial in self.dials.items():
            easing = dial['easing']
            logger.debug(f"Configuring dial `{uid}`")
            logger.debug(f"\tDial:{easing['dial_step']}% per {easing['dial_period']}ms")
            logger.debug(f"\tBacklight {easing['backlight_step']}% {easing['backlight_period']}ms")
            for target in ('dial', 'backlight'):
                self.dial_send_easing(uid, target, step=easing[f'{target}_step'],
                                      period=easing[f'{target}_period'])

    def _send(self, dial, kind, value):
        index = dial['index']
        if kind == 'value':
            return self.dial_driver.dial_single_set_percent(index, value)
        return self.dial_driver.dial_set_backlight(index, value['red'], value['green'],
                                                   value['blue'], value['white'])

    def _flush(self, kind):
        """Send each dial's pending `kind` ('value' or 'backlight') that is not backing off.

        @returns the number of dials updated
        """
        updated = 0
        now = time()
        for dial in self.dials.values():
            if not dial[f'{kind}_changed'] or self._delivery_blocked(dial, kind, now):
                continue

            # _queue replaces dial[kind] rather than mutating it, so this snapshot
            # is what went out even if the IOLoop queues a newer value mid-send.
            sent = dial[kind]
            # A NAK or timeout leaves the change pending, with backoff.
            if not self._send(dial, kind, sent):
                self._note_delivery_failure(dial, kind, now)
                continue

            # Clearing the flag over a value queued mid-send would lose it for good.
            if dial[kind] == sent:
                dial[f'{kind}_changed'] = False
            self._clear_delivery_state(dial, kind)
            updated += 1
        if updated:
            logger.debug(f"Updated {updated} dial {kind}(s).")
        return updated

    def _queue(self, dial, kind, new):
        # Short-circuit only once delivered: a pending or unresponsive dial is
        # not at this value yet, so a repeat request must re-arm the write.
        if (dial[kind] == new
                and not dial[f'{kind}_changed']
                and not dial[f'{kind}_unresponsive']):
            logger.debug(f"Dial {dial['uid']} {kind} already at {new}")
            return

        logger.debug(f"Queueing dial {dial['uid']} {kind} update to {new}")
        dial[kind] = new
        dial[f'{kind}_changed'] = True
        # A fresh request gets a clean attempt.
        self._clear_delivery_state(dial, kind)

    # -- Shared retry/backoff bookkeeping for value and backlight writes -------
    # `kind` is 'value' or 'backlight'; state lives in dial['<kind>_fail_count'],
    # dial['<kind>_retry_after'] and dial['<kind>_unresponsive'].

    def _delivery_blocked(self, dial, kind, now):
        # A dial that has exhausted its retries is left alone until it comes
        # back on a rescan or a new request re-arms it.
        if dial[f'{kind}_unresponsive']:
            return True
        # Still within the backoff window from a previous failure.
        return now < dial[f'{kind}_retry_after']

    def _note_delivery_failure(self, dial, kind, now):
        fail_count = dial[f'{kind}_fail_count'] + 1
        dial[f'{kind}_fail_count'] = fail_count
        if fail_count >= self.BACKLIGHT_MAX_FAILURES:
            dial[f'{kind}_unresponsive'] = True
            logger.error(f"Dial {dial['uid']} unresponsive after {fail_count} "
                         f"{kind} attempts; giving up until it re-appears "
                         f"or a new {kind} is requested.")
        else:
            backoff = min(self.BACKLIGHT_BACKOFF_BASE * (2 ** (fail_count - 1)),
                          self.BACKLIGHT_BACKOFF_MAX)
            dial[f'{kind}_retry_after'] = now + backoff
            logger.error(f"Failed to update {kind} for dial {dial['uid']}; "
                         f"retrying in {backoff:g}s (attempt {fail_count}).")

    @staticmethod
    def _clear_delivery_state(dial, kind):
        dial[f'{kind}_fail_count'] = 0
        dial[f'{kind}_retry_after'] = 0
        dial[f'{kind}_unresponsive'] = False

    def _periodic_update_dial_images(self):
        for _, dial in self.dials.items():
            if dial['image_changed']:
                logger.debug("Updating images")
                self.dial_driver.update_display(device=dial['index'], imageFile=dial['image_file'])
                dial['image_changed'] = False

    def provision_dials(self, num_attempts = 3):
        """Address new dials on the bus, then rescan it. Pass the result to rebuild_dials.

        @returns {bus index: UID} for the dials now on the bus
        """
        logger.debug(f"Provisioning new dials (with {num_attempts} attempts)")
        for _ in range(num_attempts):
            self.dial_driver.provision_dials()
            sleep(0.2)
        logger.debug("Retrieving list of dials")
        return self.dial_driver.get_dial_list(True)

    def reset_all_devices(self):
        """Ask the hub to reset every dial on the bus.

        A reset reboots each dial to its power-on defaults, so any cached
        "already delivered" / unresponsive backlight state is now stale. On a
        confirmed reset we re-arm each dial (value, backlight, image) and clear
        the backoff/unresponsive latch so the periodic loop pushes the desired
        state to the freshly-rebooted hardware. On failure we touch nothing --
        the hardware never reset, so the cached state is still accurate.
        """
        logger.info("Resetting all devices on the bus")
        if not self.dial_driver.reset_all_devices():
            logger.error("reset_all_devices: hub reported failure")
            return False

        for dial in self.dials.values():
            self._rearm_dial(dial)
        logger.info(f"Reset {len(self.dials)} device(s); re-armed pending updates.")
        return True

    def reset_device(self, dial_uid):
        """Software-reset a single dial.

        The hub serial protocol has no per-dial hardware power-cycle (only a
        bus-wide reset), so this clears the target dial's cached "already
        delivered" / unresponsive backlight state and re-arms its value,
        backlight and image so the periodic loop re-pushes them. This recovers
        a single dial whose backlight got stuck in a latched/backoff state
        without disturbing the rest of the bus.
        """
        dial = self._get_dial(dial_uid)
        if dial is None:
            return False

        logger.info(f"Software-resetting dial {dial_uid}")
        self._rearm_dial(dial)
        return True

    def _rearm_dial(self, dial):
        """Clear a dial's backlight backoff/unresponsive latch and mark its
        value, backlight and image dirty so the periodic loop re-pushes them."""
        dial['value_changed'] = True
        dial['backlight_changed'] = True
        dial['image_changed'] = True
        self._clear_delivery_state(dial, 'value')
        self._clear_delivery_state(dial, 'backlight')

    def get_dial_info(self, dial_uid=None):
        if dial_uid is not None:
            return self.dials.get(dial_uid, None)
        return self.dials

    def dial_set_percent(self, dial_uid, value):
        dial = self._get_dial(dial_uid)
        if dial is None:
            return False

        self._queue(dial, 'value', max(0, min(self._convert_to_int(value), 100)))
        return True

    # Debug function, mainly used for dial offset/calibration
    def dial_set_raw(self, dial_uid, value):
        dial = self._get_dial(dial_uid)
        if dial is None:
            return False

        self.dial_driver.dial_single_set_raw(dial['index'], self._convert_to_int(value))
        return True

    # Debug function, mainly used for dial offset/calibration
    def dial_set_calibration(self, dial_uid, value, fullScale=False):
        dial = self._get_dial(dial_uid)
        if dial is None:
            return False

        self.dial_driver.dial_calibrate(dial['index'], self._convert_to_int(value), fullScale)
        return True

    def dial_send_easing(self, dial_uid, target, step=None, period=None):
        """Send the easing for `target`, 'dial' (needle) or 'backlight'. Pass the result to dial_store_easing.

        @returns the sent easing fields, or None if the dial is not on the bus
        """
        dial = self._get_dial(dial_uid)
        if dial is None:
            return None

        sent = {}
        for field, value in ((f'{target}_step', step), (f'{target}_period', period)):
            if value is None:
                continue
            value = self._convert_to_int(value)
            # Driver setters are dial_easing_<field>, e.g. dial_easing_backlight_step.
            getattr(self.dial_driver, f'dial_easing_{field}')(dial['index'], value)
            sent[field] = value
        return sent

    def dial_store_easing(self, dial_uid, sent):
        """Record easing fields returned by dial_send_easing and store them in the database."""
        dial = self._get_dial(dial_uid)
        if dial is not None:
            dial['easing'] = {**dial['easing'], **sent}
        if sent:
            self.server_config.update_dial_db_cell_with_dict(
                dial_uid, {f'easing_{field}': value for field, value in sent.items()})

    def dial_set_backlight(self, dial_uid, red, green, blue, white):
        dial = self._get_dial(dial_uid)
        if dial is None:
            return False

        # Always a new dict: _flush relies on dial['backlight'] never being mutated in place.
        colour = {name: max(0, min(self._convert_to_int(level), 100))
                  for name, level in (('red', red), ('green', green), ('blue', blue), ('white', white))}
        self._queue(dial, 'backlight', colour)
        return True

    def dial_set_image(self, dial_uid, image_file):
        dial = self._get_dial(dial_uid)
        if dial is None:
            return False

        logger.debug(f"Queueing dial {dial_uid} background image to {image_file}")
        dial['image_file'] = image_file
        dial['image_changed'] = True
        return True

    def dial_set_name(self, dial_uid, name):
        """Store a dial's friendly name.

        @returns False if the dial is not on the bus or has no database row
        """
        dial = self._get_dial(dial_uid)
        if dial is None or not self.server_config.update_dial_db_cell_with_dict(dial_uid, {'dial_name': name}):
            return False

        dial['dial_name'] = name
        return True

    def dial_read_info_from_hardware(self, dial_uid):
        """Read a dial's firmware info and easing. Pass the result to dial_store_info.

        @returns {info field: value, 'easing': {...}}, or None if the dial is not on the bus
        """
        dial = self._get_dial(dial_uid)
        if dial is None:
            return None

        index = int(dial['index'])
        return {
            'fw_hash': self.dial_driver.dial_get_fw_hash(index),
            'fw_version': self.dial_driver.dial_get_fw_version(index),
            'hw_version': self.dial_driver.dial_get_hw_version(index),
            'protocol_version': self.dial_driver.dial_get_protocol_version(index),
            'easing': self.dial_driver.dial_easing_get_config(index),
        }

    def dial_store_info(self, dial_uid, info):
        """Record info returned by dial_read_info_from_hardware and store it in the database.

        @returns the dial record, or False if `info` is None or the dial is not on the bus
        """
        dial = self._get_dial(dial_uid) if info else None
        if dial is None:
            return False

        dial.update(info)
        row = {DB_COLUMNS[field]: value for field, value in info.items() if field != 'easing'}
        row.update({f'easing_{field}': info['easing'][field] for field in EASING_FIELDS})
        self.server_config.update_dial_db_cell_with_dict(dial_uid, row)
        return dial
