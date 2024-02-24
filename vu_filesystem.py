# pylint: disable=pointless-string-statement
import os
import sys
import shutil
import getpass
from vu_notifications import show_error_msg

'''
VU Server file system class

This class determines base directory for all files/paths consumed by VU Server.
It also provides a way for user/system to specify where VU Server should store data.

Note: All data files will be placed on a same/shared path.
Data files might be separated into subdirectories where it makes sense.

Base directory is defined from on of the following:

    First: System Environment Variable `VU_SERVER_DATA_PATH`
            Requirement: path is valid/exists and is writable by current process

    Second: Current user home directory
            Windows : c:/Users/USERNAME/KaranovicResearch
            Linux   : /home/USERNAME/KaranovicResearch
            Mac Os  : /Users/USERNAME/Library/KaranovicResearch
            Requirement: Path is writable by current process

    Last: VU Server install directory
            This is last-resort for storing VU server data.
            Note that application data will get removed if install directory is removed.

Transition fix:
    This change breaks current app behaviour. In order to prevent data loss and offer
    seamless transition, this class will try to migrate (copy) data from old paths
    and also mark the old files as `_migrated` (instead of removing).

'''
class FileSystem:
    base_path = None

    def __init__(self):
        potential_paths = [ os.environ.get('VU_SERVER_DATA_PATH', None),
                            self._get_user_directory(),
                            self._get_app_directory() ]

        for test_path in potential_paths:
            print(f"Testing path: {test_path}")
            if self._is_useable_path(test_path):
                self.base_path = os.path.join(test_path, 'KaranovicResearch', 'VUServer')
                break

        if self.base_path is None:
            print(f"Tested paths: {potential_paths}")
            print("Could not find useable directory for VU Server data!")
            print("Please make sure VU Server application is running with administrative privileges!")
            show_error_msg("File System Error!",
                           "Could not find useable directory for VU Server data!\n"
                           "Please make sure VU Server application is running with administrative privileges!")
            sys.exit(-1)
            # We can abort and shut-down gracefully here
            # Or try to run and pray for a miracle

        # Create required directories and files
        self._create_default_directories()
        self._create_empty_config_file()
        self._create_empty_dial_image()

        # Migrate files from pre 20240222 build
        # We should do this only once.
        # The old folder/file will have `_migrated` added to the name
        self._migrate_upload_folder()
        self._migrate_config_file()
        self._migrate_database_file()

    def _get_user_directory(self):
        # Linux
        if sys.platform in ["linux", "linux2"]:
            return f'/home/{getpass.getuser()}/KaranovicResearch'

        # MacOS
        if sys.platform == "darwin":
            return '~/Library/KaranovicResearch'

        # Windows
        if sys.platform == "win32":
            return os.path.join(os.path.expanduser(os.getenv('USERPROFILE')), 'KaranovicResearch')
        return None

    def _get_app_directory(self):
        return os.path.abspath(os.path.dirname(__file__))


    def _is_useable_path(self, test_path):
        if test_path is None:
            return False

        try:
            os.makedirs(test_path, exist_ok=True)
            if not os.path.isdir(test_path):
                print(f"{test_path} is not directory!")
                return False

            return self._is_writeable_path(test_path)
        except OSError as error:
            show_error_msg("Error while creating path!", f"Could not create`{test_path}`.\n{error}")
            print("Error while creating path!")
            print(error)
            return False

        return False

    def _is_writeable_path(self, test_path):
        try:
            # Create test file
            test_file = os.path.join(test_path, 'tmp.txt')
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write('ok')

            # Remove test file
            os.remove(test_file)

            # By this point we should assume read/write access
            return True
        except Exception as e:
            print(e)
        return False

    def _create_default_directories(self):
        os.makedirs(os.path.dirname(self.get_log_file_path()), exist_ok=True)
        os.makedirs(self.get_upload_directory_path(), exist_ok=True)

    def _create_empty_config_file(self):
        if not os.path.isfile(self.get_config_file_path()):
            with open(self.get_config_file_path(), 'w', encoding='utf-8') as f:
                f.write('server:\n')
                f.write('  hostname: localhost\n')
                f.write('  port: 5340\n')
                f.write('  communication_timeout: 10\n')
                f.write('  dial_update_period: 200\n')
                f.write('  master_key: cTpAWYuRpA2zx75Yh961Cg\n')
                f.write('\n')
                f.write('hardware:\n')
                f.write('  port: \n')
                f.write('\n')

    def _create_empty_dial_image(self):
        blank_img_path = os.path.join(self.get_upload_directory_path(), 'img_blank')
        img_data = "89504e470d0a1a0a0000000d49484452000000c800000090080000000068ee7bd8000000097048597300001ce900001\
ce901e1d0b8e5000000c649444154789cedcf410dc03010c0b03e8ec2ca1fdf508c44a55a538c209967fdc3acf776c2\
117b6e179cd288a6114d239a46348d681ad134a26944d388a6114d239a46348d681ad134a26944d388a6114d239a463\
48d681ad134a26944d388a6114d239a46348d681ad134a26944d388a6114d239a46348d681ad134a26944d388a6114d\
239a46348d681ad134a26944d388a6114d239a46348d681ad134a26944d388a6114d239a46348d681ad134a26944d38\
8a6114d239a46348d681ad1ccdab713cef8001f27036cd2b3091e0000000049454e44ae426082"

        if not os.path.isfile(blank_img_path):
            with open(blank_img_path, 'wb') as f:
                f.write(bytes.fromhex(img_data))

    def _migrate_upload_folder(self):
        # Old upload folder is at: os.path.dirname(__file__) + `upload`

        old_upload_folder = os.path.join(os.path.dirname(__file__), 'upload')
        if os.path.isdir(old_upload_folder):
            try:
                shutil.copytree(old_upload_folder, self.get_upload_directory_path(), dirs_exist_ok=True)
                shutil.move(old_upload_folder, f"{old_upload_folder}_migrated")
                print(f"Migrating upload folder: {old_upload_folder}")
                return True
            except Exception as e:
                print("Failed to copy old upload directory!")
                print(e)
                raise e
        return False # Keep pylint happy

    def _migrate_config_file(self):
        # Old config file is at: os.path.dirname(__file__)

        old_config_file = os.path.join(os.path.dirname(__file__), 'config.yaml')
        if os.path.isfile(old_config_file):
            try:
                shutil.copy(old_config_file, self.get_config_file_path())
                shutil.move(old_config_file, f"{old_config_file}_migrated")
                print(f"Migrating config file: {old_config_file}")
                return True
            except Exception as e:
                print("Failed to copy old config file!")
                print(e)
                raise e
        return False

    def _migrate_database_file(self):
        # Old config file is at: os.path.dirname(__file__)

        old_db_file = os.path.join(os.path.dirname(__file__), 'vudials.db')
        if os.path.isfile(old_db_file):
            try:
                shutil.copy(old_db_file, self.get_config_file_path())
                shutil.move(old_db_file, f"{old_db_file}_migrated")
                print(f"Migrating db file: {old_db_file}")
                return True
            except Exception as e:
                print("Failed to copy old db file!")
                print(e)
                raise e
        return False

    def get_pid_lock_file_path(self):
        return os.path.join(self.base_path)

    def get_log_file_path(self):
        return os.path.join(self.base_path, 'server.log')

    def get_database_file_path(self):
        return os.path.join(self.base_path, 'vudials.db')

    def get_config_file_path(self):
        return os.path.join(self.base_path, 'config.yaml')

    def get_upload_directory_path(self):
        return os.path.join(self.base_path, 'upload')

VU_FileSystem = FileSystem()


if __name__ == '__main__':
    vfs = FileSystem()

    print(vfs.get_log_file_path())
    print(vfs.get_database_file_path())
    print(vfs.get_config_file_path())
    print(vfs.get_upload_directory_path())
