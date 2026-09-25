import os
import secrets
import sqlite3
from dials.base_logger import logger

API_KEY_ALPHABET = 'abcdefghijkmnpqrstuvwxyz0123456789'
API_KEY_LENGTH = 16


class DialsDB:
    def __init__(self, database_file='vudials.db'):
        """Open the database next to this module, creating missing tables."""
        self.database_file = os.path.join(os.path.dirname(__file__), database_file)
        logger.info(f"VU1 Database file: {self.database_file}")

        # Only the thread that opened it, the IOLoop thread, may use the connection; sqlite3 enforces this.
        self.connection = sqlite3.connect(self.database_file)
        self.connection.row_factory = sqlite3.Row
        self._init_database()

    # -- Dial
    def fetch_dial_info_or_create_default(self, dial_uid, dial_name='Not set'):
        if self._exec("INSERT OR IGNORE INTO dials (`dial_uid`, `dial_name`) VALUES (?, ?)", (dial_uid, dial_name)):
            logger.debug(f"Added dial `{dial_uid}` to dial list with friendly name `{dial_name}`")
        return self._fetch("SELECT * FROM dials WHERE `dial_uid`=? LIMIT 1", (dial_uid,), one=True)

    def dial_update_cell_with_dict(self, dial_uid, values_dict):
        """Update columns of one dial. Keys must be trusted column names.

        @returns: True if the dial row exists.
        """
        if not isinstance(values_dict, dict):
            logger.error(f"Expecting type(dictionary) but {type(values_dict)} given.")
            return False

        logger.debug(f"Updating `{dial_uid}` to `{values_dict}`")
        fields = ', '.join(f"`{key}`=?" for key in values_dict)
        params = [*values_dict.values(), dial_uid]
        return self._exec(f"UPDATE `dials` SET {fields} WHERE `dial_uid`=?", params) > 0

    # -- API keys
    def api_key_get_id(self, key):
        res = self._fetch("SELECT `key_id` FROM `api_keys` WHERE `key_uid`=? LIMIT 1", (key,), one=True)
        return res['key_id'] if res else None

    def api_key_is_admin(self, key):
        """@returns: True if `key` is stored with admin level (99 or higher)."""
        res = self._fetch("SELECT 1 FROM `api_keys` WHERE `key_uid`=? AND `key_level` >= 99 LIMIT 1", (key,), one=True)
        return res is not None

    def api_key_list(self):
        keys = {}
        rows = self._fetch("SELECT k.*, a.dial_uid FROM api_keys k LEFT JOIN dial_access a USING(key_id) ORDER BY k.key_id, a.id")
        for row in rows:
            key = keys.setdefault(row['key_uid'], {
                'key_name': row['key_name'],
                'key_uid': row['key_uid'],
                'priviledges': int(row['key_level']),
                'dials': [],
            })
            if row['dial_uid'] is not None:
                key['dials'].append(row['dial_uid'])
        return keys

    def api_key_get_dial_access(self, key_id):
        rows = self._fetch("SELECT `dial_uid` FROM `dial_access` WHERE `key_id`=?", (key_id,))
        return [row['dial_uid'] for row in rows]

    def api_key_add_dial_access(self, key, dials):
        """Replace the set of dials a key may access."""
        key_id = self.api_key_get_id(key)
        if not key_id or not dials:
            return False

        with self.connection:
            self.connection.execute("DELETE FROM `dial_access` WHERE `key_id`=?", (key_id,))
            cursor = self.connection.executemany(
                "INSERT OR IGNORE INTO `dial_access` (dial_uid, key_id) VALUES (?, ?)",
                [(dial, key_id) for dial in dials])
            return cursor.rowcount > 0

    def api_update_master(self, new_key):
        """Store the config.yaml master key as key_id 1."""
        return self._exec("INSERT OR REPLACE INTO api_keys (key_id, key_name, key_uid, key_level) VALUES ('1', 'MASTER_KEY', ?, 99)", (new_key,)) > 0

    def api_key_generate(self, key_name='Not set'):
        # key_uid is UNIQUE, so a colliding key fails the insert and is redrawn.
        # Any other integrity error is re-raised so it cannot loop forever.
        while True:
            generated_key = self.generate_api_key_str()
            try:
                self._exec("INSERT INTO api_keys (`key_uid`, `key_name`, `key_level`) VALUES (?, ?, 1)",
                           (generated_key, key_name))
                return generated_key
            except sqlite3.IntegrityError:
                if self.api_key_get_id(generated_key) is None:
                    raise

    def generate_api_key_str(self):
        return ''.join(secrets.choice(API_KEY_ALPHABET) for _ in range(API_KEY_LENGTH))

    def api_key_update(self, key_uid, key_name=None):
        if key_name is None:
            return False
        return self._exec("UPDATE `api_keys` SET `key_name`=? WHERE `key_uid`=?", (key_name, key_uid)) > 0

    def api_key_delete(self, key_uid):
        """Delete a non-master key and its dial access.

        @returns: True if the key was deleted.
        """
        with self.connection:
            self.connection.execute(
                "DELETE FROM `dial_access` WHERE `key_id` IN "
                "(SELECT `key_id` FROM `api_keys` WHERE `key_uid`=? AND `key_level` < 99)", (key_uid,))
            cursor = self.connection.execute(
                "DELETE FROM `api_keys` WHERE `key_uid`=? AND `key_level` < 99", (key_uid,))
            return cursor.rowcount > 0

    # -- Internal
    def _exec(self, sql, params=()):
        """Run one write statement in its own transaction.

        @returns: the number of rows changed.
        """
        with self.connection:
            return self.connection.execute(sql, params).rowcount

    def _fetch(self, sql, params=(), one=False):
        cursor = self.connection.execute(sql, params)
        return cursor.fetchone() if one else cursor.fetchall()

    def _init_database(self):
        with self.connection:
            self.connection.execute("""
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

            self.connection.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                                                         key_id INTEGER UNIQUE PRIMARY KEY AUTOINCREMENT ,
                                                         key_name TEXT,
                                                         key_uid TEXT NOT NULL UNIQUE,
                                                         key_level INTEGER)
                    """)

            self.connection.execute("""
                    CREATE TABLE IF NOT EXISTS dial_access (
                                                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                            dial_uid TEXT NOT NULL,
                                                            key_id INTEGER NOT NULL)
                    """)
