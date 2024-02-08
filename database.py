import os
import sqlite3
import random
from dials.base_logger import logger

class DialsDB:
    connection = None

    def __init__(self, database_path, init_if_missing=False):

        if not os.path.exists(database_path):
            os.makedirs(database_path)

        self.database_file = os.path.join(database_path, 'vudials.db')
        logger.info(f"VU1 Database file: {self.database_file}")

        if not os.path.exists(self.database_file) and not init_if_missing:
            raise SystemError("Database file does not exist!")

        self.connection = sqlite3.connect(self.database_file)
        self.connection.row_factory = sqlite3.Row

        if init_if_missing:
            self._init_database()

    # -- Dial
    def fetch_dial_info_or_create_default(self, dial_uid, dial_name='Not set'):

        # check if dial exists
        res = self._fetch_one_query(f"SELECT * FROM dials WHERE `dial_uid`='{dial_uid}' LIMIT 1")
        if not res:
            self._insert(f"INSERT INTO dials (`dial_uid`, `dial_name`) VALUES ('{dial_uid}', '{dial_name}')")
            logger.debug(f"Added dial `{dial_uid}` to dial list with friendly name `{dial_name}`")
            res = self._fetch_one_query(f"SELECT * FROM dials WHERE `dial_uid`='{dial_uid}' LIMIT 1")

        return res

    def dial_update_cell(self, dial_uid, cell, value):
        logger.debug(f"Updating `{dial_uid}` to `{cell}`='{value}'")

        logger.debug(f"Attempting to update `{dial_uid}` to `{cell}='{value}'")
        self._insert(f"UPDATE dials SET `{cell}`='{value}' WHERE `dial_uid`='{dial_uid}'")

        return self._more_than_one_changed()

    def dial_update_cell_with_dict(self, dial_uid, values_dict):
        if not isinstance(values_dict, dict):
            logger.error(f"Expecting type(dictionary) but {type(values_dict)} given.")
            return 0

        logger.debug(f"Updating `{dial_uid}` to `{values_dict}'")

        fields = ', '.join( f"`{key}`='{value}'" for key, value in values_dict.items())
        query = f"UPDATE `dials` SET {fields} WHERE `dial_uid`='{dial_uid}'"
        logger.debug(query)

        logger.debug(f"Attempting to update `{dial_uid}` to `{values_dict}'")
        self._insert(query)

        return self._more_than_one_changed()

    # -- API keys
    def api_key_get_id(self, key):
        res = self._fetch_one(table='api_keys', cell='key_id', where='key_uid', where_cmp=key, limit=1)
        if not res:
            return None
        return res[0]

    def api_key_list(self):
        api_keys = {}
        db_keys = self._fetch_all("SELECT * FROM api_keys")

        if not db_keys:
            return api_keys

        for key in list(db_keys):
            item = {}
            item = {'key_name': key['key_name'], 'key_uid': key['key_uid'], 'priviledges': int(key['key_level'])}
            item['dials'] = self.api_key_get_dial_access(key['key_id'])
            api_keys[key['key_uid']] = item

        return api_keys

    def api_key_get_dial_access(self, key_id):
        dials = []

        key_access = self._fetch_all(f"SELECT `dial_uid` FROM `dial_access` WHERE `key_id`='{key_id}'")

        if not key_access:
            return dials

        for item in key_access:
            dials.append(item['dial_uid'])

        return dials

    def api_key_add_dial_access(self, key, dials):
        key_id = self.api_key_get_id(key)
        if not key_id:
            return False

        if not dials:
            return False

        # Wipe any existing entries that key has
        self._query(f"DELETE FROM `dial_access` WHERE `key_id`={key_id}")

        # Add dial access
        for dial in dials:
            self._insert(f"INSERT OR IGNORE INTO `dial_access` (dial_uid, key_id) VALUES ('{dial}', '{key_id}')")

        return self._more_than_one_changed()


    # Set master key to defined value (used to drive master key from .yaml file into sqlite database)
    def api_update_master(self, new_key):
        self._query(f"INSERT OR REPLACE INTO api_keys (key_id, key_name, key_uid, key_level) VALUES ('1', 'MASTER_KEY', '{new_key}', 99)")
        return self._more_than_one_changed()

    def api_key_generate(self, key_name='Not set', level=1):
        generated_key = self.generate_api_key_str()
        while self._fetch_one(table='api_keys', cell='key_id', where='key_uid', where_cmp=generated_key, limit=1):
            generated_key = self.generate_api_key_str()

        # self._insert(f"INSERT INTO api_keys (`key_uid`, `key_name`, `key_level`) VALUES ('{generated_key}', '{key_name}', '{level}')")
        table_data = { 'key_uid': generated_key, 'key_name': key_name, 'key_level': level }
        self._insert_dict('api_keys', table_data)
        if self._more_than_one_changed():
            return generated_key
        raise SystemError("Failed to generate and store new API key to database!")

    def generate_api_key_str(self):
        s = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'm', 'n', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z',
                '0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
        return ''.join(random.sample(s, 16))

    def api_key_update(self, key_uid, key_name=None, level=None):
        # Find key in DB
        key_id = self.api_key_get_id(key_uid)

        query_update_level = ""
        if level is not None:
            query_update_level = f", `key_level`='{level}'"

        # Rename key
        if key_name is not None:
            self._query(f"UPDATE `api_keys` SET `key_name`='{key_name}' {query_update_level} WHERE `key_id`='{key_id}'")
            return self._more_than_one_changed()
        return False

    def api_key_delete(self, key_uid):
        # Make sure we are not deleting master key!
        res = self._fetch_one_query(f"SELECT `key_id` FROM `api_keys` WHERE `key_uid`='{key_uid}' AND `key_level` < '99' LIMIT 1")
        key_id = res['key_id']
        if not key_id:
            return False

        # Delete the KEY
        query = f"DELETE FROM `api_keys` WHERE `key_id`='{key_id}'"
        logger.debug(query)
        self._query(query)
        self._commit()
        if self._more_than_one_changed():
            # Delete dial access
            self._query(f"DELETE FROM `dial_access` WHERE `key_id`='{key_id}'")
            self._commit()

            return self._more_than_one_changed()

        return False


    # -- Internal
    def _insert_dict(self, table_name, dict_data):
        cursor = self.connection.cursor()
        attrib_names = ", ".join(dict_data.keys())
        attrib_values = ", ".join("?" * len(dict_data.keys()))
        sql = f"INSERT INTO {table_name} ({attrib_names}) VALUES ({attrib_values})"
        cursor.execute(sql, list(dict_data.values()))
        self._commit()

    def _commit(self):
        self.connection.commit()

    def _insert(self, query):
        self._query(query)
        self.connection.commit()

    def _query(self, query):
        cursor = self.connection.cursor()
        cursor.execute(query)

    def _fetch_one(self, table, cell, where, where_cmp, limit=1):
        cursor = self.connection.cursor()
        query = f"SELECT {cell} FROM {table} WHERE {where} ='{where_cmp}' LIMIT {limit}"
        logger.debug(query)
        cursor.execute(query)
        return cursor.fetchone()

    def _fetch_one_query(self, query):
        cursor = self.connection.cursor()
        cursor.execute(query)
        return cursor.fetchone()

    def _fetch_all(self, query):
        cursor = self.connection.cursor()
        cursor.execute(query)
        return cursor.fetchall()


    def _more_than_one_changed(self):
        if self.connection.total_changes > 0:
            return True
        return False

    def _init_database(self):
        # Create DIALS table
        self._query("""
                    CREATE TABLE IF NOT EXISTS dials (
                                                    "dial_id" INTEGER PRIMARY KEY AUTOINCREMENT,
                                                    "dial_uid" TEXT NOT NULL UNIQUE,
                                                    "dial_name" TEXT DEFAULT 'Not Set',
                                                    "dial_gen" TEXT DEFAULT 'VU1',
                                                    "dial_build_hash" TEXT DEFAULT '?',
                                                    "dial_fw_version" TEXT DEFAULT '?',
                                                    "dial_hw_version" TEXT DEFAULT '?',
                                                    "dial_protocol_version" TEXT DEFAULT 'V1',
                                                    "easing_dial_step" INTEGER DEFAULT 2,
                                                    "easing_dial_period" INTEGER DEFAULT 50,
                                                    "easing_backlight_step" INTEGER DEFAULT 5,
                                                    "easing_backlight_period" DEFAULT 100
                                                  )
                    """)

        # Create API KEYS table
        self._query("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                                                         key_id INTEGER UNIQUE PRIMARY KEY AUTOINCREMENT ,
                                                         key_name TEXT,
                                                         key_uid TEXT NOT NULL UNIQUE,
                                                         key_level INTEGER)
                    """)

        # Create DIAL ACCESS table
        self._query("""
                    CREATE TABLE IF NOT EXISTS dial_access (
                                                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                            dial_uid TEXT NOT NULL,
                                                            key_id INTEGER NOT NULL)
                    """)

        self.connection.commit()
