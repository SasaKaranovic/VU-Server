import os
from time import time, sleep
from math import trunc
from dials.base_logger import logger

# ServerDialHandler Class
# ---
# This class handles all the requests coming from the server.
# It stores update requests (value, backlight, image etc) that are coming from the server API calls.
# It will also periodically update the dials
# ---
# 'periodic_dial_update' function is called periodically from the main server loop
#
class ServerDialHandler:
    dials = {}
    hub_info = {}
    communication_timeout = 3

    def __init__(self, dial_driver, server_config):
        self.dial_driver = dial_driver
        self.server_config = server_config

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
            logger.error("Failed to convert value `{value}`to int. Defaulting to 0")
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
        for dial in dials:
            dial['value'] = 0
            dial['backlight'] = {'red':0, 'green':0, 'blue':0, 'white':0 }
            dial['image_file'] = self._check_upload_for_dial_image(dial['uid'])
            dial['update_deadline'] = time()
            dial['value_changed'] = False
            dial['backlight_changed'] = True
            dial['image_changed'] = False
            self.dials[dial['uid']] = dial

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
        filename = f'img_{dial_uid}'
        filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'upload', filename)
        if os.path.exists(filepath):
            return filename

        return 'img_blank'

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
        for _, dial in self.dials.items():
            if dial['backlight_changed']:
                self.dial_driver.dial_set_backlight(dial['index'],
                                                    dial['backlight']['red'],
                                                    dial['backlight']['green'],
                                                    dial['backlight']['blue'],
                                                    dial['backlight']['white']
                                                    )
                dial['backlight_changed'] = False
                dial['update_deadline'] = time() + self.communication_timeout
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

    def get_dial_info(self, dial_uid=None):
        if dial_uid is not None:
            return self.dials.get(dial_uid, None)
        return self.dials

    def dial_set_percent(self, dial_uid, value):
        if not self._dial_exists(dial_uid):
            logger.error(f"Dial {dial_uid} does not exist in dial list.")
            return False

        value = self._convert_to_int(value)

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

        red = min(red, 100)
        green = min(green, 100)
        blue = min(blue, 100)
        blue = min(blue, 100)
        white = min(white, 100)

        new_value = {'red':red, 'green':green, 'blue':blue, 'white':white }

        # Check if already at value
        if self.dials[dial_uid]['backlight'] == new_value:
            logger.debug(f"Dial {dial_uid} already at {red}:{green}:{blue}:{white}")
            return True

        logger.debug(f"Queueing dial {dial_uid} RGBW update to {red}:{green}:{blue}:{white}")
        self.dials[dial_uid]['backlight'] = {'red':red, 'green':green, 'blue':blue, 'white':white }
        self.dials[dial_uid]['backlight_changed'] = True
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
        logger.error(dial_info)

        self.dials[dial_uid]['fw_hash'] = dial_info['dial_build_hash']
        self.dials[dial_uid]['fw_version'] = dial_info['dial_fw_version']
        self.dials[dial_uid]['hw_version'] = dial_info['dial_hw_version']
        self.dials[dial_uid]['protocol_version'] = dial_info['dial_protocol_version']
        self.dials[dial_uid]['easing']['dial_step'] = dial_info['easing_dial_step']
        self.dials[dial_uid]['easing']['dial_period'] = dial_info['easing_dial_period']
        self.dials[dial_uid]['easing']['backlight_step'] = dial_info['easing_backlight_step']
        self.dials[dial_uid]['easing']['backlight_period'] = dial_info['easing_backlight_period']

        return self.dials[dial_uid]
