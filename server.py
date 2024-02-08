import sys
import os
import signal
import argparse
import zlib
import time
from mimetypes import guess_type
from dials.base_logger import logger, set_logger_level
from tornado.web import Application, RequestHandler, Finish, StaticFileHandler
from tornado.ioloop import IOLoop, PeriodicCallback
from dial_driver import DialSerialDriver
from server_config import ServerConfig
from server_dial_handler import ServerDialHandler
from vu_notifications import show_error_msg, show_info_msg

BASEDIR_NAME = os.path.dirname(__file__)
BASEDIR_PATH = os.path.abspath(BASEDIR_NAME)
WEB_ROOT = os.path.join(BASEDIR_PATH, 'www')

def pid_lock(service_name, create=True):
    file_name = "service.{}.pid.lock".format(service_name)
    pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)

    if create:
        pid = os.getpid()
        with open(pid_file, "w", encoding="utf-8") as file:
            file.write(str(pid))
    else:
        if os.path.exists(pid_file):
            os.remove(pid_file)

class BaseHandler(RequestHandler):
    def initialize(self, handler, config):
        self.handler = handler # pylint: disable=attribute-defined-outside-init
        self.config = config # pylint: disable=attribute-defined-outside-init
        self.upload_path = os.path.join(os.path.dirname(__file__), 'upload') # pylint: disable=attribute-defined-outside-init

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        # self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        # self.set_header('Access-Control-Allow-Methods', ' PUT, DELETE, OPTIONS, GET')
        self.set_header('Access-Control-Allow-Methods', 'POST, GET')
        self.set_header('Content-Type', 'application/json')

        # self.set_header("Access-Control-Allow-Origin", "Origin");
        # self.set_header("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization");
        # self.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        # self.set_header("Access-Control-Allow-Credentials", "true");

    # Helper function to send response
    def send_response(self, status, message='', data=None, status_code=200):
        resp = {'status': status, 'message': message, 'data': data}
        self.set_status(status_code)
        self.write(resp)
        self.finish()

    def api_key_has_access_to_dial(self, gaugeUID, api_key=None):
        if api_key is None:
            api_key = self.get_argument('key', None)

        if not self.config.api_key_has_access_to_dial(api_key, gaugeUID):
            return False
        return True

    def is_valid_api_key(self):
        if not self.config.is_valid_api_key(self.get_argument('key', None)):
            return False
        return True

    def valid_admin_key(self):
        admin_key = self.get_argument('admin_key', None)
        if not admin_key:
            logger.error("Missing API key")
            self.send_response(status='fail', message='Invalid or missing API key.', status_code=401)
            return False

        if not self.config.validate_admin_key(admin_key):
            logger.error("Invalid API key")
            self.send_response(status='fail', message='Invalid or missing API key.', status_code=401)
            return False
        return True

    def get_file_crc(self, filepath):
        if not os.path.exists(filepath):
            logger.error(f"File {filepath} does not exist!")
            return "00000000"

        with open(filepath, 'rb') as fh:
            fileCrc = 0
            while True:
                s = fh.read(65536)
                if not s:
                    break
                fileCrc = zlib.crc32(s, fileCrc)
        return "%08X" % (fileCrc & 0xFFFFFFFF)


class Device_Status_Handler(BaseHandler):
    def get(self, dial_uid):
        logger.debug(f"Request:STATUS - Device:{dial_uid}")
        dial = self.handler.get_dial_info(dial_uid=dial_uid)
        if dial is not None:
            return self.send_response(status='ok', data=dial)
        return self.send_response(status='fail', message='Invalid dial_uid or device is offline.')

class Device_Set_Handler(BaseHandler):
    def get(self, dial_uid):
        value = self.get_argument('value', 0)
        logger.debug(f"Request:SET - Device:{dial_uid} To:{value}")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        if self.handler.dial_set_percent(dial_uid=dial_uid, value=value):
            return self.send_response(status='ok', message='Update queued')
        return self.send_response(status='fail', message='Invalid dial_uid or device is offline.')

class Device_SetRaw_Handler(BaseHandler):
    def get(self, dial_uid):
        value = self.get_argument('value', 0)
        logger.debug(f"Request:SET_RAW - Device:{dial_uid} To:{value}")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        if self.handler.dial_set_raw(dial_uid=dial_uid, value=value):
            return self.send_response(status='ok', message='Dial RAW value updated', status_code=201)
        return self.send_response(status='fail', message='Invalid dial_uid or device is offline.', status_code=503)

class Device_Backlight_Handler(BaseHandler):
    def get(self, dial_uid):
        red = self.get_argument('red', 0)
        green = self.get_argument('green', 0)
        blue = self.get_argument('blue', 0)
        white = self.get_argument('white', 0)

        logger.debug(f"Request:BACKLIGHT - Device:{dial_uid} To: (red:{red} green:{green} blue:{blue} white:{white})")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        if self.handler.dial_set_backlight(dial_uid=dial_uid, red=red, green=green, blue=blue, white=white):
            return self.send_response(status='ok', message='Update queued', status_code=201)
        return self.send_response(status='fail', message='Invalid dial_uid or device is offline.', status_code=503)

class Device_Set_Image(BaseHandler):
    def post(self, dial_uid):
        get_force = self.get_argument('force', False)

        force_img_update = bool(get_force is True)

        logger.debug(f"Request:SET_IMAGE - Device:{dial_uid}")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        # Store new image
        img_file = self.handle_image_upload(dial_uid)
        if not img_file:
            logger.error("Handle image upload failed")
            return self.send_response(status='fail', message='image upload failed', status_code=503)

        current_img = os.path.join(self.upload_path, f'img_{dial_uid}')
        new_img = os.path.join(self.upload_path, f'tmp_{dial_uid}')

        # If this is a different image from existing one
        if self.different_image_uploaded(current_img, new_img) or force_img_update:

            # Remove existing image (if exists)
            if os.path.exists(current_img):
                os.remove(current_img)
            # Move (rename) new image and set as current
            os.rename(new_img, current_img)


            if self.handler.dial_set_image(dial_uid=dial_uid, image_file=current_img):
                return self.send_response(status='ok', status_code=201)
            return self.send_response(status='fail', message='Invalid dial_uid or device is offline.', status_code=503)

        logger.debug(f"Skipping dial `{dial_uid}` image update. Contents already match.")
        return self.send_response(status='ok', message='Image CRC already maches existing one. Skipping update.')

    def handle_image_upload(self, dial_uid):
        self.make_upload_folder()
        image_data = self.request.files.get('imgfile', None)
        if image_data is None:
            logger.error("imgfile field missing from request.")
            return None

        # First upload image as temporary
        file_path = os.path.join(self.upload_path, f'tmp_{dial_uid}')

        with open(file_path, 'wb') as img:
            img.write(image_data[0]['body'])

        return file_path

    def different_image_uploaded(self, old, new):
        if self.get_file_crc(old) != self.get_file_crc(new):
            return True
        return False

    def make_upload_folder(self):
        if not os.path.exists(self.upload_path):
            os.makedirs(self.upload_path)

class Dial_Get_Image(BaseHandler):
    def get(self, gaugeUID):
        self.set_header("Content-Type", "image/png")

        logger.debug("Request: GET_IMAGE")
        dial_image = os.path.join(os.path.dirname(__file__), 'upload', f'img_{gaugeUID}')

        if os.path.exists(dial_image):
            filepath = dial_image
            logger.debug(f"Serving image from {filepath}")
        else:
            filepath = os.path.join(os.path.dirname(__file__), 'upload', 'img_blank')
            logger.debug(f"Serving DEFAULT image from {filepath}")

        try:
            with open(filepath, 'rb') as f:
                data = f.read()
                self.write(data)
            return self.finish()
        except IOError as e:
            logger.error(e)
            return self.send_response(status='fail', message='Internal sever error!', status_code=500)

class Dial_Get_Image_CRC(BaseHandler):
    def get(self, gaugeUID):
        logger.debug("Request: GET_IMAGE_CRC")

        img_file = os.path.join(os.path.dirname(__file__), 'upload', f'img_{gaugeUID}')

        crc = self.get_file_crc(img_file)
        return self.send_response(status='ok', data=crc)

class Dial_Get_List(BaseHandler):
    def get(self):
        logger.debug("Request: DEVICE_LIST")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Missing API key!', status_code=403)

        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        dials = self.handler.get_dial_info()
        # logger.debug(dials)

        # Reshape dials data to respond with only relevant information
        dialData = []
        for uid in dials:
            tmp_dial =  {
                            'uid' : uid,
                            'dial_name': dials[uid]['dial_name'],
                            'value': dials[uid]['value'],
                            'backlight': dials[uid]['backlight'],
                            'image_file' : dials[uid]['image_file']
                        }
            # Remove unused keys
            tmp_dial['backlight'].pop('white', None)

            # If key has access to dial
            if self.api_key_has_access_to_dial(gaugeUID=uid):
                dialData.append(tmp_dial)

        return self.send_response(status='ok', data=dialData)


class Dial_Provision(BaseHandler):
    def get(self):

        logger.debug("Request: PROVISION_NEW_DIALS")

        # Validate master key
        if not self.valid_admin_key():
            return False

        dials = self.handler.provision_dials()
        logger.debug(dials)

        return self.send_response(status='ok', data=dials)

class Dial_Set_Dial_Name(BaseHandler):
    def get(self, gaugeUID):
        new_name = self.get_argument('name', None)
        logger.debug(f"Request:SET_NAME - Device:{gaugeUID} To: friendly name={new_name}")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        if new_name is not None:
            self.config.update_dial_db_cell(dial_uid=gaugeUID, cell='dial_name', value=new_name)
            return self.send_response(status='ok', status_code=201)
        return self.send_response(status='fail', message='Device not present!', status_code=406)

class Dial_Reload_Device_Info(BaseHandler):
    def get(self, gaugeUID):

        logger.debug(f"Request:GET_INFO - Device:{gaugeUID}")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        dial_info = self.handler.dial_reload_info_from_hardware(gaugeUID)
        return self.send_response(status='ok', data=dial_info)

class Dial_Set_Calibration(BaseHandler):
    def get(self, gaugeUID):
        dac_calibration = self.get_argument('value', None)
        logger.debug(f"Request:SET_CALIBRATION - Device:{gaugeUID} To: value={dac_calibration}")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        if dac_calibration is not None:
            self.handler.dial_set_calibration(dial_uid=gaugeUID, value=dac_calibration, fullScale=False)
            return self.send_response(status='ok', message="Calibration value updated", status_code=201)
        return self.send_response(status='fail', message="Device not present", status_code=406)

class Dial_Set_Easing_Dial(BaseHandler):
    def get(self, gaugeUID):
        step = self.get_argument('step', None)
        period = self.get_argument('period', None)
        logger.debug(f"Request:SET_EASING_DIAL - Device:{gaugeUID} Step:{step} Period:{period}")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        if step is None and period is None:
            return self.send_response(status='fail', message="Please provide at least one of required parameters (`step` or `period`)", status_code=400)

        if self.handler.dial_set_easing_dial(dial_uid=gaugeUID, step=step, period=period):
            values_dict = { 'easing_dial_step': int(step), 'easing_dial_period': int(period) }
            self.config.update_dial_db_cell_with_dict(gaugeUID, values_dict)
            self.handler.dial_reload_info_from_database(gaugeUID)
            return self.send_response(status='ok')
        return self.send_response(status='fail', message="Device not present", status_code=406)

class Dial_Set_Easing_Backlight(BaseHandler):
    def get(self, gaugeUID):
        step = self.get_argument('step', None)
        period = self.get_argument('period', None)
        logger.debug(f"Request:SET_EASING_BACKLIGHT - Device:{gaugeUID} Step:{step} Period:{period}")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        if step is None and period is None:
            return self.send_response(status='fail', message="Please provide at least one of required parameters (`step` or `period`)", status_code=400)

        if self.handler.dial_set_easing_backlight(dial_uid=gaugeUID, step=step, period=period):
            values_dict = { 'easing_backlight_step': step, 'easing_backlight_period': period }
            self.config.update_dial_db_cell_with_dict(gaugeUID, values_dict)
            self.handler.dial_reload_info_from_database(gaugeUID)
            return self.send_response(status='ok')
        return self.send_response(status='fail', message="Device not present", status_code=406)

class Dial_Get_Easing_Config(BaseHandler):
    def get(self, gaugeUID):
        logger.debug(f"Request:GET_EASING_CONFIG - Device:{gaugeUID}")

        # Validate API key
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Unauthorized', status_code=401)

        # TODO: Implement in dial handler
        return self.send_response(status='ok', message="not supported yet")

# -- Keys --
class Admin_Keys_List(BaseHandler):
    def get(self):
        logger.debug("Request:Admin_Keys_List")

        # Validate master key
        if not self.valid_admin_key():
            return False # Above function already sends response

        keys = self.config.list_keys()

        ret = []
        for _, value in keys.items():
            # value.pop('dials', None)
            ret.append(value)
        return self.send_response(status='ok', data=ret)

class Admin_Keys_Create(BaseHandler):
    def post(self):
        logger.debug("Request:Admin_Keys_Create")

        # Validate master key
        if not self.valid_admin_key():
            return False # Above function already sends response

        key_name    = self.get_argument('name', 'Not set')
        dial_access = self.get_argument('dials', None)
        priviledges = self.get_argument('priviledges', 1)

        if dial_access:
            dials = dial_access.split(';')
        else:
            dials = None

        new_key = self.config.create_api_key(key_name, priviledges)

        if dials:
            self.config.api_key_add_dial_access(new_key, dials)

        return self.send_response(status='ok', data=new_key)

class Admin_Keys_Update(BaseHandler):
    def post(self):
        logger.debug("Request:Admin_Keys_Update")

        dial_list = self.get_argument('dials', None)
        key = self.get_argument('key', None)
        name = self.get_argument('name', None)

        # Validate master key
        if not self.valid_admin_key():
            return False # Above function already sends response

        # Check if API key exists
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Invalid key selected!')

        logger.debug(dial_list)
        logger.debug(key)
        logger.debug(name)

        if dial_list is None and key is None:
            return self.send_response(status='fail', message='Key, Key name and Dial list are all empty. Aborting.', status_code=400)

        # Update key
        if name is not None:
            if not self.config.update_api_key(key_uid=key, key_name=name):
                return self.send_response(status='fail', message='Failed to update key!')

        # Update dial access
        if dial_list:
            dial_list = dial_list.split(';')
            if self.config.api_key_add_dial_access(key, dial_list):
                return self.send_response(status='ok', message='Key updated!')

        return self.send_response(status='fail', message='Failed to update key!')

class Admin_Keys_Remove(BaseHandler):
    def get(self):
        logger.debug("Request:Admin_Keys_Remove")
        key_uid = self.get_argument('key', None)

        # Validate master key
        if not self.valid_admin_key():
            return False # Above function already sends response

        # Check if API key exists
        if not self.is_valid_api_key():
            return self.send_response(status='fail', message='Invalid key selected!')

        if not self.config.delete_api_key(key_uid):
            return self.send_response(status='fail', message='Failed to remove key!')
        return self.send_response(status='ok', message='Key removed!')

# -- Default 404 --
class Default_404_Handler(RequestHandler):
    # Override prepare() instead of get() to cover all possible HTTP methods.
    def prepare(self):
        self.set_status(404)
        resp = {'status': 'fail', 'message': 'Unsupported method'}
        self.write(resp)
        raise Finish()

class FileHandler(RequestHandler):
    def get(self, path=None):
        if path:
            logger.debug(f"Requesting: {path}")
            file_location = os.path.join(WEB_ROOT, path)
        else:
            file_location = os.path.join(WEB_ROOT, 'index.html')

        if not os.path.isfile(file_location):
            logger.error(f"Requested file can not be found: {path}")
            self.set_status(404)
            resp = {'status': 'fail', 'message': 'Page not found'}
            self.write(resp)
            raise Finish()
        content_type, _ = guess_type(file_location)
        self.add_header('Content-Type', content_type)
        with open(file_location, encoding="utf-8") as source_file:
            self.write(source_file.read())


class Dial_API_Service(Application):
    def __init__(self):
        pid_lock('server', True)

        logger.info("Loading server config...")
        self.config = ServerConfig('config.yaml')

        # If config contains COM port, use it. Otherwise try to find it
        hardware_config = self.config.get_hardware_config()
        port = hardware_config.get('port', None)
        if port:
            self.serialPort = port
        else:
            self.serialPort = DialSerialDriver.find_gauge_hub()
            if self.serialPort is None:
                logger.error("Could not find VU1 Dials Hub. Please make sure it's plugged in and (if necessary) drivers are installed.")
                show_error_msg("Hub not found", "Could not find VU1 Hub on the USB bus.\r\n"\
                               "Please make sure it is plugged in and (if necessary) drivers are installed.\r\n"\
                               "Then restart the VU Server application.\r\nVU server application will close now.")
                sys.exit(0)
                # raise Exception("Could not find VU1 Dials Hub. Please make sure it's plugged in and (if necessary) drivers are installed.")

        logger.info("VU1 HUB port: {}".format(self.serialPort))
        self.dial_driver = DialSerialDriver(self.serialPort)
        self.dial_handler = ServerDialHandler(self.dial_driver, self.config)

        # If we don't see any dials, try looking/provisioning some
        if len(self.dial_handler.dials) <= 1:
            logger.info("No additional dials found. Searching the bus for new ones...")
            self.dial_handler.provision_dials(num_attempts=3)

        handlers_config = { "handler":self.dial_handler, "config":self.config }
        self.handlers = [
            (r"/api/v0/dial/provision", Dial_Provision, handlers_config),
            (r"/api/v0/dial/list", Dial_Get_List, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/status", Device_Status_Handler, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/set", Device_Set_Handler, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/setRaw", Device_SetRaw_Handler, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/image/set", Device_Set_Image, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/image/get", Dial_Get_Image, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/image/crc", Dial_Get_Image_CRC, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/backlight", Device_Backlight_Handler, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/name", Dial_Set_Dial_Name, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/reload", Dial_Reload_Device_Info, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/calibrate", Dial_Set_Calibration, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/easing/dial", Dial_Set_Easing_Dial, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/easing/backlight", Dial_Set_Easing_Backlight, handlers_config),
            (r"/api/v0/dial/([0-9A-F]*?)/easing/get", Dial_Get_Easing_Config, handlers_config),
            (r"/api/v0/admin/keys/list", Admin_Keys_List, handlers_config),
            (r"/api/v0/admin/keys/create", Admin_Keys_Create, handlers_config),
            (r"/api/v0/admin/keys/remove", Admin_Keys_Remove, handlers_config),
            (r"/api/v0/admin/keys/update", Admin_Keys_Update, handlers_config),
            (r"/", FileHandler),
            (r'/(.*)', StaticFileHandler, {'path': WEB_ROOT}),
        ]

        self.server_settings = {
            "debug": True,
            "autoreload": False,
            # "autoreload": True,
            "default_handler_class": Default_404_Handler,
        }

    def run_forever(self):
        logger.info("Karanovic Research Dials - Starting API server")
        app = Application(self.handlers, **self.server_settings)

        # Port from config.yaml or default 5340
        server_config = self.config.get_server_config()
        port = server_config.get('port', 5340)
        master_key = server_config.get('master_key', None)
        dial_update_period = server_config.get('dial_update_period', 1000)
        logger.info(f"VU1 API server is listening on http://localhost:{port}")
        app.listen(port)

        if master_key is not None:
            logger.info("Master Key is present in config.yaml (or using default)")
            logger.info(f"Provide '{master_key}' to your main application.")
            logger.info("to allow it to manage this server and the VU dials.")
        else:
            show_error_msg(title='Key missing from config', message='Entry "master_key" is missing from the "config.yaml"!')
            logger.error("Master Key is MISSING from config.yaml")
            logger.error("Check your 'config.yaml' or add it manually under 'server' section.")
            sys.exit(0)

        pc = PeriodicCallback(self.dial_handler.periodic_dial_update, dial_update_period)
        pc.start()

        IOLoop.instance().start()


def signal_handler(signal, frame):
    pid_lock('server', False)
    IOLoop.current().add_callback_from_signal(shutdown)
    print('\r\nYou pressed Ctrl+C!')
    show_info_msg("CTRL+C", "CTRL+C pressed.\r\nVU Server app will exit now.")  # Remove if becomes annoying
    sys.exit(0)

def shutdown():
    logger.info('Stopping API server')

    logger.info('Will shutdown in 3 seconds ...')
    io_loop = IOLoop.instance()
    deadline = time.time() + 3

    def stop_loop():
        now = time.time()
        if now < deadline and (io_loop._callbacks or io_loop._timeouts):
            io_loop.add_timeout(now + 1, stop_loop)
        else:
            io_loop.stop()
            logger.info('Shutdown')
    stop_loop()


def main(cmd_args=None):
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    if cmd_args is None:
        set_logger_level('info')
    else:
        set_logger_level(cmd_args.logging)
    try:
        Dial_API_Service().run_forever()
    except Exception:
        logger.exception("VU Dials API service crashed during setup.")
        show_error_msg("Crashed", "VU Server has crashed unexpectedly!\r\nPlease check log files for more information.")
    os._exit(0)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Karanovic Research - VU Dials API service')
    parser.add_argument('-l', '--logging', type=str, default='info', help='Set logging level. Default is `info`')
    args = parser.parse_args()
    main(args)
