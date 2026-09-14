import os
import sqlite3
import random
from threading import RLock
from dials.base_logger import logger

class DialsDB:
    connection = None
    database_changes = 0

    def __init__(self, database_file='vudials.db', init_if_missing=False):
        # Serial I/O is offloaded to a worker thread, and provision/reload
        # persist dial info to the DB from that thread. Allow cross-thread use
        # of the connection and serialize every access with a reentrant lock so
        # concurrent statements from the IOLoop thread and the serial worker
        # can't collide on the same connection.
        self._lock = RLock()
        # database_path = os.path.join(os.path.expanduser('~'), 'KaranovicResearch', 'vudials')
        database_path = os.path.join(os.path.dirname(__file__))

        if not os.path.exists(database_path):
            os.makedirs(database_path)

        self.database_file =  os.path.join(database_path, database_file)
        logger.info(f"VU1 Database file: {self.database_file}")

        if not os.path.exists(self.database_file) and not init_if_missing:
            raise SystemError("Database file does not exist!")

        self.connection = sqlite3.connect(self.database_file, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row

        if init_if_missing:
            self._init_database()

    # -- Dial
    def fetch_dial_info_or_create_default(self, dial_uid, dial_name='Not set'):

        # check if dial exists
        res = self._fetch_one_query("SELECT * FROM dials WHERE `dial_uid`=? LIMIT 1", (dial_uid,))
        if not res:
            self._insert("INSERT INTO dials (`dial_uid`, `dial_name`) VALUES (?, ?)", (dial_uid, dial_name))
            logger.debug(f"Added dial `{dial_uid}` to dial list with friendly name `{dial_name}`")
            res = self._fetch_one_query("SELECT * FROM dials WHERE `dial_uid`=? LIMIT 1", (dial_uid,))

        return res

    def dial_update_cell(self, dial_uid, cell, value):
        logger.debug(f"Updating `{dial_uid}` to `{cell}`='{value}'")

        logger.debug(f"Attempting to update `{dial_uid}` to `{cell}='{value}'")
        self._insert(f"UPDATE dials SET `{cell}`=? WHERE `dial_uid`=?", (value, dial_uid))

        return self._more_than_one_changed()

    def dial_update_cell_with_dict(self, dial_uid, values_dict):
        if not isinstance(values_dict, dict):
            logger.error(f"Expecting type(dictionary) but {type(values_dict)} given.")
            return 0

        logger.debug(f"Updating `{dial_uid}` to `{values_dict}'")

        fields = ', '.join(f"`{key}`=?" for key in values_dict.keys())
        query = f"UPDATE `dials` SET {fields} WHERE `dial_uid`=?"
        params = list(values_dict.values()) + [dial_uid]
        logger.debug(query)

        logger.debug(f"Attempting to update `{dial_uid}` to `{values_dict}'")
        self._insert(query, params)

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

        key_access = self._fetch_all("SELECT `dial_uid` FROM `dial_access` WHERE `key_id`=?", (key_id,))

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
        self._query("DELETE FROM `dial_access` WHERE `key_id`=?", (key_id,))

        # Add dial access
        for dial in dials:
            self._insert("INSERT OR IGNORE INTO `dial_access` (dial_uid, key_id) VALUES (?, ?)", (dial, key_id))

        return self._more_than_one_changed()


    # Set master key to defined value (used to drive master key from .yaml file into sqlite database)
    def api_update_master(self, new_key):
        self._insert("INSERT OR REPLACE INTO api_keys (key_id, key_name, key_uid, key_level) VALUES ('1', 'MASTER_KEY', ?, 99)", (new_key,))
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

        # Rename key
        if key_name is not None:
            if level is not None:
                self._query("UPDATE `api_keys` SET `key_name`=?, `key_level`=? WHERE `key_id`=?", (key_name, level, key_id))
            else:
                self._query("UPDATE `api_keys` SET `key_name`=? WHERE `key_id`=?", (key_name, key_id))
            return self._more_than_one_changed()
        return False

    def api_key_delete(self, key_uid):
        # Make sure we are not deleting master key!
        res = self._fetch_one_query("SELECT `key_id` FROM `api_keys` WHERE `key_uid`=? AND `key_level` < '99' LIMIT 1", (key_uid,))
        if not res:
            return False
        key_id = res['key_id']

        # Delete the KEY
        query = "DELETE FROM `api_keys` WHERE `key_id`=?"
        logger.debug(query)
        self._query(query, (key_id,))
        self._commit()
        if self._more_than_one_changed():
            # Delete dial access. This may affect zero rows (a key without any
            # granted dials), so its change count must NOT decide the return
            # value -- the key itself was already deleted successfully.
            self._query("DELETE FROM `dial_access` WHERE `key_id`=?", (key_id,))
            self._commit()
            self._more_than_one_changed()  # keep the change counter in sync

            return True

        return False


    # -- Internal
    def _insert_dict(self, table_name, dict_data):
        with self._lock:
            cursor = self.connection.cursor()
            attrib_names = ", ".join(dict_data.keys())
            attrib_values = ", ".join("?" * len(dict_data.keys()))
            sql = f"INSERT INTO {table_name} ({attrib_names}) VALUES ({attrib_values})"
            cursor.execute(sql, list(dict_data.values()))
            self._commit()

    def _commit(self):
        with self._lock:
            self.connection.commit()

    def _insert(self, query, params=()):
        with self._lock:
            self._query(query, params)
            self.connection.commit()

    def _query(self, query, params=()):
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(query, params)

    # `table`, `cell` and `where` are always internal column/table names, never
    # user-supplied, so it's safe to interpolate them; only `where_cmp` (the
    # value being compared) needs to go through a bound parameter.
    def _fetch_one(self, table, cell, where, where_cmp, limit=1):
        query = f"SELECT {cell} FROM {table} WHERE {where} =? LIMIT {limit}"
        logger.debug(query)
        return self._fetch_one_query(query, (where_cmp,))

    def _fetch_one_query(self, query, params=()):
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()

    def _fetch_all(self, query, params=()):
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()


    def _more_than_one_changed(self):
        with self._lock:
            if self.connection.total_changes > self.database_changes:
                self.database_changes = self.connection.total_changes
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
