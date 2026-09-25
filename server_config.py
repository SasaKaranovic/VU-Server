import hmac
import os
from ruamel.yaml import YAML
from dials.base_logger import logger
from vu_notifications import notify
import database as db

SERVER_DEFAULTS = {'hostname': 'localhost', 'port': 5340, 'dial_update_period': 200, 'master_key': 'cTpAWYuRpA2zx75Yh961Cg'}
HARDWARE_DEFAULTS = {'port': None}

class ServerConfig:
    def __init__(self, config_file='config.yaml'):
        self.config_path = os.path.join(os.path.dirname(__file__), config_file)
        self.server = None
        self.hardware = None

        logger.info(f"VU1 config yaml file: {self.config_path}")
        self.database = db.DialsDB()
        self._load_config()
        # key_id 1 always holds the current master key, so a rotated key stops working.
        self.database.api_update_master(self.server['master_key'])
        self.debug_config()

    def _load_config(self):
        """Load config.yaml, filling missing keys and invalid sections from the defaults.

        An empty `server.hostname` stays empty and means all interfaces.
        """
        cfg = {}
        if not os.path.exists(self.config_path):
            notify('error', "Can not find config.yaml", f"Config file '{self.config_path}' is missing!\r\n"\
                   "Using default values for this session.")
        else:
            with open(self.config_path, 'r', encoding="utf-8") as file:
                cfg = YAML(typ='safe', pure=True).load(file)  # pylint: disable=assignment-from-no-return
            if not isinstance(cfg, dict):
                notify('warning', "Invalid config file", f"Config file '{self.config_path}' is empty or corrupt!\r\n"\
                       "Using default values for this session.")
                cfg = {}

        self.server = self._merge_section(cfg, 'server', SERVER_DEFAULTS)
        self.hardware = self._merge_section(cfg, 'hardware', HARDWARE_DEFAULTS)

        if self.server['hostname'] is None:
            self.server['hostname'] = ''
        if self.server['master_key'] is None or str(self.server['master_key']) == '':
            notify('warning', "Empty master key", f"Config file '{self.config_path}' has an empty `server.master_key`.\r\n"\
                   "Using the default master key for this session.")
            self.server['master_key'] = SERVER_DEFAULTS['master_key']
        self.server['master_key'] = str(self.server['master_key'])

    def _merge_section(self, cfg, name, defaults):
        section = cfg.get(name)
        if not isinstance(section, dict):
            if cfg:
                notify('warning', "Invalid config", f"Config file '{self.config_path}' has no valid `{name}` section.\r\n"\
                       f"Using default `{name}` values for this session.")
            section = {}
        elif missing := [key for key in defaults if key not in section]:
            logger.info(f"Config `{name}` has no {', '.join(missing)}; using defaults.")
        return {**defaults, **section}

    def update_dial_db_cell_with_dict(self, dial_uid, values_dict):
        """@returns: True if the dial has a database row, which was updated."""
        try:
            return self.database.dial_update_cell_with_dict(dial_uid=dial_uid, values_dict=values_dict)
        except Exception as e:
            logger.error(e)
            return False

    def dial_fetch_db_info(self, dial_uid):
        return self.database.fetch_dial_info_or_create_default(dial_uid)

    def debug_config(self):
        logger.debug("--- Server Config ---")
        logger.debug(f"\t Host: {self.server['hostname']}")
        logger.debug(f"\t Port: {self.server['port']}")
        logger.debug(f"\t Dial update period: {self.server['dial_update_period']}")

    def get_server_config(self):
        return self.server

    def get_hardware_config(self):
        return self.hardware

    def create_api_key(self, key_name):
        generated_key = self.database.api_key_generate(key_name=key_name)
        logger.info(f"Generated API key '{generated_key}' (key_name:'{key_name}')")
        return generated_key

    def update_api_key(self, key_uid, key_name):
        return self.database.api_key_update(key_uid=key_uid, key_name=key_name)

    def delete_api_key(self, key_uid):
        return self.database.api_key_delete(key_uid=key_uid)

    def list_keys(self):
        return self.database.api_key_list()

    def api_key_add_dial_access(self, key, dials):
        return self.database.api_key_add_dial_access(key, dials)

    def validate_admin_key(self, key):
        """@returns: True if `key` is the configured master key or a stored admin-level key."""
        if not isinstance(key, str):
            return False
        # Existing databases can hold level-99 keys, which the API can no longer create; they stay admin.
        return (hmac.compare_digest(key.encode(), self.server['master_key'].encode())
                or self.database.api_key_is_admin(key))

    def is_valid_api_key(self, key):
        return key is not None and self.database.api_key_get_id(key) is not None

    def api_key_has_access_to_dial(self, key, dial):
        """@returns: True if `key` is an admin key or has been granted `dial`."""
        if self.validate_admin_key(key):
            return True
        key_id = self.database.api_key_get_id(key) if key is not None else None
        return key_id is not None and dial in self.database.api_key_get_dial_access(key_id)
