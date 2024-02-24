# pylint: disable=E1101
import os
from ruamel.yaml import YAML
# import yaml
from dials.base_logger import logger
from vu_notifications import show_error_msg, show_warning_msg
from vu_filesystem import VU_FileSystem
import database as db

class ServerConfig:
    config_path = None
    server = None
    hardware = None
    server_default = {'hostname': 'localhost', 'port': 3000, 'communication_timeout': 10, 'master_key': 'cTpAWYuRpA2zx75Yh961Cg' }
    hardware_default = {'port': None }
    dials = {}
    api_keys = {}
    database = None

    def __init__(self):
        self.config_path =  VU_FileSystem.get_config_file_path()
        logger.info(f"VU1 config yaml file: {self.config_path}")
        self.database = db.DialsDB(init_if_missing=True)
        self._load_config()     # Load configuration from .yaml file
        self._load_API_keys()   # Load API keys from `api_keys` section
        self.debug_config()

    # Save current configuration to .yaml file
    def _save_config(self):
        config = None
        yaml = YAML(typ='safe', pure=True)

        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding="utf-8") as file:
                config = yaml.load(file) # pylint: disable=assignment-from-no-return

        if not config:
            config = {}

        # Update server config
        if not config.get('server'):
            config['server'] = self.server
            config['port'] = self.server['port']
            config['communication_timeout'] = 5000
        else:
            config['server']['hostname'] = self.server['hostname']
            config['server']['port'] = self.server['port']
            config['server']['communication_timeout'] = self.server['communication_timeout']

        with open(self.config_path, 'w', encoding="utf-8") as file:
            yaml.dump(config, file)

    # Read .yaml config file
    def _load_config(self):
        if not os.path.exists(self.config_path):
            logger.error(f"Can not load config. Config file '{self.config_path}' does not exist!")
            show_error_msg("Can not find config.yaml", f"Config file '{self.config_path}' is missing!\r\n"\
                           "Please fix this issue by creating a default config.yaml file in the VU Server directory.\r\n"\
                           "Using default values for this session.")
            self._create_default_config()
            return False

        yaml = YAML(typ='safe', pure=True)
        with open(self.config_path, 'r', encoding="utf-8") as file:
            cfg = yaml.load(file)  # pylint: disable=assignment-from-no-return

        if cfg is None:
            show_error_msg("Empty/corrupt config file!", "Config file exists but it is empty or corrupt!\r\n"\
                           "Using defaul values for this session.")
            self._create_default_config()
            return False

        # Check that config file meets the minimum requirements
        if not isinstance(cfg, dict) or 'server' not in cfg or 'hardware' not in cfg:
            show_warning_msg("Missing Key", f"Config file '{self.config_path}' \r\n"\
                             "Must have valid entries for 'server' and 'hardware' configuration!\r\n"\
                             "Using defaul values for this session.")
            cfg = {}
            cfg['server'] = self.server_default
            cfg['hardware'] = self.hardware_default

        elif not isinstance(cfg['server'], dict):
            show_warning_msg("Invalid server config", f"Config file '{self.config_path}' \r\n"\
                             "Has invalid `server` config entry.\r\n"\
                             "Using defaul values for this session.")
            self._force_default_config()
            return False

        elif not isinstance(cfg['hardware'], dict):
            show_warning_msg("Invalid server config", f"Config file '{self.config_path}' \r\n"\
                             "Has invalid `hardware` config entry.\r\n"\
                             "Using defaul values for this session.")
            self._force_default_config()
            return False

        elif ('hostname' not in cfg['server'] or
             'port' not in cfg['server'] or
             'communication_timeout' not in cfg['server'] or
             'master_key' not in cfg['server']):
            show_warning_msg("Missing Key", f"Config file '{self.config_path}' \r\n"\
                             "must have `hostname`, `port`, `communication_timeout` and `master_key` entries!\r\n"\
                             "Using defaul values for this session.")
            self._force_default_config()
            return False

        elif 'port' not in cfg['hardware']:
            show_warning_msg("Missing Key", f"Config file '{self.config_path}' \r\n"\
                             "must have hardware `port` entry! (it can be left empty)\r\n"\
                             "Using defaul values for this session.")
            self._force_default_config()
            return False

        # Load yaml values
        self.server = cfg.get('server', self.server_default)
        self.hardware = cfg.get('hardware', self.hardware_default)

        return True

    def _force_default_config(self):
        self.server = self.server_default
        self.hardware = self.hardware_default

    def _create_default_config(self):
        logger.info("Using default config values")
        self.server = self.server_default
        self.hardware = self.hardware_default

    # Load API keys from config file
    def _load_API_keys(self):
        # Make sure .yaml master key exists in the database
        self.database.api_update_master(self.server['master_key'])

        # Load all API keys from the database
        self.api_keys = self.database.api_key_list()

    def reload_API_keys(self):
        # Load all API keys from the database
        self.api_keys = self.database.api_key_list()

    def update_dial_db_cell(self, dial_uid, cell, value):
        try:
            ret = self.database.dial_update_cell(dial_uid=dial_uid, cell=cell, value=value)
            if ret:
                self.dials[dial_uid][cell] = value
                return True
            return False
        except Exception as e:
            logger.error(e)
            return False

    def update_dial_db_cell_with_dict(self, dial_uid, values_dict):
        try:
            self.database.dial_update_cell_with_dict(dial_uid=dial_uid, values_dict=values_dict)
        except Exception as e:
            logger.error(e)
            return

    # Read dial information stored in the DB and append to existing list
    def append_dial_info_from_db(self, dial_list):
        for key, dial in enumerate(dial_list):
            dial_info = self.database.fetch_dial_info_or_create_default(dial['uid'])

            dial_list[key]['dial_name'] = dial_info['dial_name']
            dial_list[key]['fw_hash'] = dial_info['dial_build_hash']
            dial_list[key]['fw_version'] = dial_info['dial_fw_version']
            dial_list[key]['hw_version'] = dial_info['dial_hw_version']
            dial_list[key]['protocol_version'] = dial_info['dial_protocol_version']
            dial_list[key]['easing']['dial_step'] = dial_info['easing_dial_step']
            dial_list[key]['easing']['dial_period'] = dial_info['easing_dial_period']
            dial_list[key]['easing']['backlight_step'] = dial_info['easing_backlight_step']
            dial_list[key]['easing']['backlight_period'] = dial_info['easing_backlight_period']

            self.dials[dial['uid']] = dial

        return dial_list

    def dial_fetch_db_info(self, dial_uid):
        return self.database.fetch_dial_info_or_create_default(dial_uid)

    # Print out .yaml config
    def debug_config(self):
        logger.debug(f"\t Host: {self.server['hostname']}")
        logger.debug("--- Server Config ---")
        logger.debug(f"\t Port: {self.server['port']}")
        logger.debug(f"\t Serial Timeout: {self.server['communication_timeout']}")
        logger.debug(f"\t Master Key: {self.server['master_key']}")

        logger.debug("--- API Keys ---")
        logger.debug(f"\t There are {len(self.api_keys)} API keys loaded")

    def get_server_config(self):
        return self.server

    def get_hardware_config(self):
        return self.hardware

    def create_api_key(self, key_name, priviledges=0):
        generated_key = self.database.api_key_generate(key_name=key_name, level=priviledges)
        logger.info(f"Generated API key '{generated_key}' (key_name:'{key_name}', priviledges:'{priviledges}')")
        self.list_keys(reload=True)
        return generated_key

    def update_api_key(self, key_uid, key_name):
        # Update key
        if not self.database.api_key_update(key_uid=key_uid, key_name=key_name):
            return False
        return True

    def delete_api_key(self, key_uid):
        if not self.database.api_key_delete(key_uid=key_uid):
            return False
        self.list_keys(reload=True)
        return True

    def list_keys(self, reload=False):
        if reload:
            self.api_keys = self.database.api_key_list()
        return self.api_keys

    def api_key_add_dial_access(self, key, dials):
        res = self.database.api_key_add_dial_access(key, dials)
        if res:
            self.list_keys(reload=True)
        return res

    # Returns True if provided key is listed as master key
    # Otherwise return False
    def validate_admin_key(self, key):
        if not self.is_valid_api_key(key):
            logger.debug(f"API key `{key}` does not exist")
            return False

        if self.api_keys[key]['priviledges'] >= 99:
            return True
        logger.debug("Key exists but not admin key.")
        return False


    # Returns True if API key existis, otherwise returns False
    def is_valid_api_key(self, key):
        if key in self.api_keys.keys():
            return True
        return False

    # Returns True if API key has access to dial UID, otherwise retrns False
    def api_key_has_access_to_dial(self, key, dial):
        if not self.is_valid_api_key(key):
            return False

        # Master key has wildcard access
        if self.api_keys[key]['priviledges'] >= 99:
            return True

        if dial in self.api_keys[key]['dials']:
            return True
        return False
