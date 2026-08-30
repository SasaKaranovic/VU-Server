import os
from time import time, sleep
from math import trunc
from dials.base_logger import logger

# Where Device_Set_Image stores per-dial images (`img_<uid>`) and where the
# shipped fallback `img_blank` lives.
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'upload')

# ServerDialHandler Class
# ---
# This class handles all the requests coming from the server.
# It stores update requests (value, backlight, image etc) that are coming from the server API calls.
# It will also periodically update the dials
# ---
# 'periodic_dial_update' function is called periodically from the main server loop
#
class ServerDialHandler:
    communication_timeout = 3

    # Backlight retry-backoff. A dial that stops ACKing backlight writes is
    # retried with exponential backoff; after BACKLIGHT_MAX_FAILURES consecutive
    # failures it is marked unresponsive and left alone until it re-appears on a
    # bus rescan or a new colour is requested. This keeps one dead dial from
    # spamming the log and blocking the serial bus on every periodic tick.
    BACKLIGHT_MAX_FAILURES = 5
    BACKLIGHT_BACKOFF_BASE = 1.0   # seconds
    BACKLIGHT_BACKOFF_MAX = 30.0   # seconds

    def __init__(self, dial_driver, server_config):
        self.dial_driver = dial_driver
        self.server_config = server_config

        # Per-instance state (previously class attributes shared across every
        # ServerDialHandler instance).
        self.dials = {}
        self.hub_info = {}

        # Communication timeout
        cfg = self.server_config.get_server_config()
        self.communication_timeout = cfg.get('communication_timeout', 3)
        logger.info(f"Communication timeout set to {self.communication_timeout} seconds")

        logger.debug("Retrieving list of dials")
        self._reload_dials(True)

        logger.debug("Reconfiguring dials with stored behaviour")
        self._send_db_config_to_dials()

        logger.debug("Setting all dials percentage to 0")
        self.dial_driver.set_all_dials_to(0)

        logger.debug("Server dial handler up and running.")

    def periodic_dial_update(self):
        updated = 0
        ret=0

        ret = self._periodic_update_dial_values()
        updated = updated + ret

        ret = self._periodic_update_dial_backlight()
        updated = updated + ret

        ret = self._periodic_update_dial_images()
        updated = updated + ret

        if updated <=0:
            self._periodic_keep_alive()

    def _convert_to_int(self, value):
        try:
            if not isinstance(value, int):
                value = trunc(int(float(value)))
        except Exception as e:
            logger.error(e)
            logger.error(f"Failed to convert value `{value}` to int. Defaulting to 0")
            value = 0

        return value

    def _reload_dials(self, rescan=False):
        # Get dial list from the dial driver (actual list reported from the hub)
        dials = self.dial_driver.get_dial_list(rescan)

        if len(dials)<=0:
            logger.error("No dials connected to the bus!")
            return

        # 1 - Inform config/db what is the list of dials that we currently see
        # 2 - Update handler information with any information retrieved from the database
        # dials = self.server_config.append_dial_info_from_db(dials)
        self.server_config.append_dial_info_from_db(dials)

        # Dial HUB uses indexes to address each dial. On the server side we use UID for flexibility
        # and also so that we can uniquely identify each dial.
        # Rebuild from the current bus scan so dials that were unplugged no
        # longer show up in the API's dial list.
        refreshed = {}
        for dial in dials:
            dial['value'] = 0
            dial['backlight'] = {'red':0, 'green':0, 'blue':0, 'white':0 }
            dial['image_file'] = self._check_upload_for_dial_image(dial['uid'])
            dial['update_deadline'] = time()
            dial['value_changed'] = False
            dial['backlight_changed'] = True
            dial['backlight_fail_count'] = 0
            dial['backlight_retry_after'] = 0
            dial['backlight_unresponsive'] = False
            dial['image_changed'] = False
            refreshed[dial['uid']] = dial
        self.dials = refreshed

    def _send_db_config_to_dials(self):
        for _, dial in self.dials.items():
            dial_step = dial['easing']['dial_step']
            dial_period = dial['easing']['dial_period']
            backlight_step = dial['easing']['backlight_step']
            backlight_period = dial['easing']['backlight_period']

            logger.debug(f"Configuring dial `{dial['uid']}`")
            logger.debug(f"\tDial:{dial_step}% per {dial_period}ms")
            logger.debug(f"\tBacklight {backlight_step}% {backlight_period}ms")
            self.dial_set_easing_dial(dial['uid'], step=dial_step, period=dial_period)
            self.dial_set_easing_backlight(dial['uid'], step=backlight_step, period=backlight_period)

    def _check_upload_for_dial_image(self, dial_uid):
        # Always return an absolute path: this value is handed straight to
        # DialSerialDriver.display_send_image when the dial is re-armed by a
        # reset. Returning the bare filename made that lookup relative to the
        # process CWD, so it never found the file and the display -- already
        # cleared by update_display -- was left blank.
        filepath = os.path.join(UPLOAD_DIR, f'img_{dial_uid}')
        if os.path.exists(filepath):
            return filepath

        return os.path.join(UPLOAD_DIR, 'img_blank')

    # TODO: Update to send multiple/all dial values in one go instead one-by-one
    def _periodic_update_dial_values(self):
        updated = 0
        for _, dial in self.dials.items():
            if dial['value_changed']:
                self.dial_driver.dial_single_set_percent(dial['index'], dial['value'])
                dial['value_changed'] = False
                dial['update_deadline'] = time() + self.communication_timeout
                updated = updated+1
        if updated>0:
            logger.debug(f"Updated {updated} dial values.")
        return updated

    def _periodic_update_dial_backlight(self):
        updated = 0
        now = time()
        for _, dial in self.dials.items():
            if not dial['backlight_changed']:
                continue

            # A dial that has exhausted its retries is left alone until it comes
            # back on a rescan or a new colour is queued (see dial_set_backlight).
            if dial.get('backlight_unresponsive', False):
                continue

            # Still within the backoff window from a previous failure.
            if now < dial.get('backlight_retry_after', 0):
                continue

            sent = self.dial_driver.dial_set_backlight(dial['index'],
                                                dial['backlight']['red'],
                                                dial['backlight']['green'],
                                                dial['backlight']['blue'],
                                                dial['backlight']['white']
                                                )
            # Only mark the update as delivered if the driver confirmed the
            # write. Clearing the flag on a failed send would leave the cached
            # RGBW state out of sync with the hardware, and the "already at
            # value" short-circuit in dial_set_backlight() would then block
            # re-sending the same colour indefinitely.
            if not sent:
                fail_count = dial.get('backlight_fail_count', 0) + 1
                dial['backlight_fail_count'] = fail_count
                if fail_count >= self.BACKLIGHT_MAX_FAILURES:
                    dial['backlight_unresponsive'] = True
                    logger.error(f"Dial {dial['uid']} unresponsive after {fail_count} "
                                 f"backlight attempts; giving up until it re-appears "
                                 f"or a new colour is requested.")
                else:
                    backoff = min(self.BACKLIGHT_BACKOFF_BASE * (2 ** (fail_count - 1)),
                                  self.BACKLIGHT_BACKOFF_MAX)
                    dial['backlight_retry_after'] = now + backoff
                    logger.error(f"Failed to update backlight for dial {dial['uid']}; "
                                 f"retrying in {backoff:g}s (attempt {fail_count}).")
                continue

            dial['backlight_changed'] = False
            dial['backlight_fail_count'] = 0
            dial['backlight_retry_after'] = 0
            dial['backlight_unresponsive'] = False
            dial['update_deadline'] = now + self.communication_timeout
            updated = updated+1
        if updated>0:
            logger.debug(f"Updated {updated} dial backlight(s).")
        return updated

    def _periodic_update_dial_images(self):
        updated = 0
        for _, dial in self.dials.items():
            if dial['image_changed']:
                logger.debug("Updating images")
                self.dial_driver.update_display(device=dial['index'], imageFile=dial['image_file'])
                dial['update_deadline'] = time() + self.communication_timeout
                dial['image_changed'] = False
                updated = updated+1
        return updated

    def _periodic_keep_alive(self):
        #FIXME!
        return
        # for _, dial in self.dials.items():
            # if time() >= dial['update_deadline']:
                # logger.info("Keeping communication alive")
                # self.dial_driver.dial_send_keep_comm_alive(device=dial['index'])
                # dial['image_changed'] = False

    def _dial_exists(self, dial_uid):
        return dial_uid in self.dials

    def provision_dials(self, num_attempts = 3):
        logger.debug(f"Provisioning new dials (with {num_attempts} attempts)")
        for _ in range(num_attempts):
            self.dial_driver.provision_dials()
            sleep(0.2)
        logger.debug("Retrieving list of dials")
        self._reload_dials(True)
        return self.get_dial_info()

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
        if not self._dial_exists(dial_uid):
            logger.error(f"reset_device: dial {dial_uid} does not exist.")
            return False

        logger.info(f"Software-resetting dial {dial_uid}")
        self._rearm_dial(self.dials[dial_uid])
        return True

    def _rearm_dial(self, dial):
        """Clear a dial's backlight backoff/unresponsive latch and mark its
        value, backlight and image dirty so the periodic loop re-pushes them."""
        dial['value_changed'] = True
        dial['backlight_changed'] = True
        dial['image_changed'] = True
        dial['backlight_fail_count'] = 0
        dial['backlight_retry_after'] = 0
        dial['backlight_unresponsive'] = False
        dial['update_deadline'] = time()

    def get_dial_info(self, dial_uid=None):
        if dial_uid is not None:
            return self.dials.get(dial_uid, None)
        return self.dials

    def dial_set_percent(self, dial_uid, value):
        if not self._dial_exists(dial_uid):
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
            return False

        value = self._convert_to_int(value)
        value = max(0, min(value, 100))

        # Check if already at value
        if self.dials[dial_uid]['value'] == value:
            logger.debug(f"Dial {dial_uid} already at {value}")
            return True

        logger.debug(f"Queueing dial {dial_uid} value update to {value}")
        self.dials[dial_uid]['value'] = value
        self.dials[dial_uid]['value_changed'] = True
        return True

    # Debug function, mainly used for dial offset/calibration
    def dial_set_raw(self, dial_uid, value):
        if not self._dial_exists(dial_uid):
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
            return False

        value = self._convert_to_int(value)
        self.dial_driver.dial_single_set_raw(self.dials[dial_uid]['index'], value)
        return True


    # Debug function, mainly used for dial offset/calibration
    def dial_set_calibration(self, dial_uid, value, fullScale=False):
        if not self._dial_exists(dial_uid):
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
            return False

        value = self._convert_to_int(value)
        self.dial_driver.dial_calibrate(self.dials[dial_uid]['index'], value, fullScale)
        return True

    def dial_set_easing_dial(self, dial_uid, step=None, period=None):
        if not self._dial_exists(dial_uid):
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
            return False

        if step is not None:
            step = self._convert_to_int(step)
            self.dial_driver.dial_easing_dial_step(self.dials[dial_uid]['index'], step)

        if period is not None:
            period = self._convert_to_int(period)
            self.dial_driver.dial_easing_dial_period(self.dials[dial_uid]['index'], period)

        return True

    def dial_set_easing_backlight(self, dial_uid, step=None, period=None):
        if not self._dial_exists(dial_uid):
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
            return False

        if step is not None:
            step = self._convert_to_int(step)
            self.dial_driver.dial_easing_backlight_step(self.dials[dial_uid]['index'], step)

        if period is not None:
            period = self._convert_to_int(period)
            self.dial_driver.dial_easing_backlight_period(self.dials[dial_uid]['index'], period)

        return True

    def dial_set_backlight(self, dial_uid, red, green, blue, white):
        if not self._dial_exists(dial_uid):
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
            return False

        red = self._convert_to_int(red)
        green = self._convert_to_int(green)
        blue = self._convert_to_int(blue)
        white = self._convert_to_int(white)

        red = max(0, min(red, 100))
        green = max(0, min(green, 100))
        blue = max(0, min(blue, 100))
        white = max(0, min(white, 100))

        new_value = {'red':red, 'green':green, 'blue':blue, 'white':white }

        dial = self.dials[dial_uid]

        # Only short-circuit when the value has actually been delivered. If a
        # change is still pending or the dial was marked unresponsive, the
        # hardware is not at this colour yet, so re-requesting it must re-arm the
        # write instead of being silently dropped.
        if (dial['backlight'] == new_value
                and not dial['backlight_changed']
                and not dial.get('backlight_unresponsive', False)):
            logger.debug(f"Dial {dial_uid} already at {red}:{green}:{blue}:{white}")
            return True

        logger.debug(f"Queueing dial {dial_uid} RGBW update to {red}:{green}:{blue}:{white}")
        dial['backlight'] = {'red':red, 'green':green, 'blue':blue, 'white':white }
        dial['backlight_changed'] = True
        # A fresh request clears any prior backoff / unresponsive state so the
        # dial gets a clean attempt.
        dial['backlight_fail_count'] = 0
        dial['backlight_retry_after'] = 0
        dial['backlight_unresponsive'] = False
        return True

    def dial_set_image(self, dial_uid, image_file):
        if not self._dial_exists(dial_uid):
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
            return False

        logger.debug(f"Queueing dial {dial_uid} background image to {image_file}")
        self.dials[dial_uid]['image_file'] = image_file
        self.dials[dial_uid]['image_changed'] = True
        return True

    def dial_reload_info_from_hardware(self, dial_uid):
        if not self._dial_exists(dial_uid):
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
            return False

        deviceIndex = int(self.dials[dial_uid]['index'])

        fw_hash = self.dial_driver.dial_get_fw_hash(deviceIndex)
        fw_version = self.dial_driver.dial_get_fw_version(deviceIndex)
        hw_version = self.dial_driver.dial_get_hw_version(deviceIndex)
        protocol_version = self.dial_driver.dial_get_protocol_version(deviceIndex)
        deviceEasing = self.dial_driver.dial_easing_get_config(deviceIndex)   # Read dial easing config

        self.dials[dial_uid]['fw_hash'] = fw_hash
        self.dials[dial_uid]['fw_version'] = fw_version
        self.dials[dial_uid]['hw_version'] = hw_version
        self.dials[dial_uid]['protocol_version'] = protocol_version
        self.dials[dial_uid]['easing']['dial_step'] = deviceEasing['dial_step']
        self.dials[dial_uid]['easing']['dial_period'] = deviceEasing['dial_period']
        self.dials[dial_uid]['easing']['backlight_step'] = deviceEasing['backlight_step']
        self.dials[dial_uid]['easing']['backlight_period'] = deviceEasing['backlight_period']

        self.server_config.update_dial_db_cell(dial_uid, 'dial_build_hash', fw_hash)
        self.server_config.update_dial_db_cell(dial_uid, 'dial_fw_version', fw_version)
        self.server_config.update_dial_db_cell(dial_uid, 'dial_hw_version', hw_version)
        self.server_config.update_dial_db_cell(dial_uid, 'dial_protocol_version', protocol_version)
        self.server_config.update_dial_db_cell(dial_uid, 'easing_dial_step', deviceEasing['dial_step'])
        self.server_config.update_dial_db_cell(dial_uid, 'easing_dial_period', deviceEasing['dial_period'])
        self.server_config.update_dial_db_cell(dial_uid, 'easing_backlight_step', deviceEasing['backlight_step'])
        self.server_config.update_dial_db_cell(dial_uid, 'easing_backlight_period', deviceEasing['backlight_period'])

        return self.dials[dial_uid]


    def dial_reload_info_from_database(self, dial_uid):
        if not self._dial_exists(dial_uid):
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
            return False

        dial_info = self.server_config.dial_fetch_db_info(dial_uid)

        self.dials[dial_uid]['fw_hash'] = dial_info['dial_build_hash']
        self.dials[dial_uid]['fw_version'] = dial_info['dial_fw_version']
        self.dials[dial_uid]['hw_version'] = dial_info['dial_hw_version']
        self.dials[dial_uid]['protocol_version'] = dial_info['dial_protocol_version']
        self.dials[dial_uid]['easing']['dial_step'] = dial_info['easing_dial_step']
        self.dials[dial_uid]['easing']['dial_period'] = dial_info['easing_dial_period']
        self.dials[dial_uid]['easing']['backlight_step'] = dial_info['easing_backlight_step']
        self.dials[dial_uid]['easing']['backlight_period'] = dial_info['easing_backlight_period']

        return self.dials[dial_uid]
