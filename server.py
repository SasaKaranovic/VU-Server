import sys
import os
import signal
import argparse
import zlib
import re
import functools
from concurrent.futures import ThreadPoolExecutor
from dials.base_logger import logger, configure_logging
from tornado.web import Application, RequestHandler, Finish, StaticFileHandler
from tornado.ioloop import IOLoop, PeriodicCallback
from dial_driver import DialSerialDriver
from server_config import ServerConfig
from server_dial_handler import ServerDialHandler
from vu_notifications import notify
from serial.serialutil import SerialException

BASEDIR_NAME = os.path.dirname(__file__)
BASEDIR_PATH = os.path.abspath(BASEDIR_NAME)
WEB_ROOT = os.path.join(BASEDIR_PATH, 'www')

# Public fields /status returns; the rest of the dial record is internal state.
STATUS_FIELDS = ('uid', 'index', 'dial_name', 'value', 'backlight', 'image_file', 'easing',
                 'fw_hash', 'fw_version', 'hw_version', 'protocol_version',
                 'value_changed', 'backlight_changed', 'image_changed')

class BaseHandler(RequestHandler):
    # Credential prepare() demands: None, 'key' (any API key), 'dial' (an API
    # key granted the dial in the first path argument) or 'admin' (master key).
    auth = None

    def initialize(self, handler, config, executor=None):
        self.handler = handler # pylint: disable=attribute-defined-outside-init
        self.config = config # pylint: disable=attribute-defined-outside-init
        # Dedicated single-worker executor for blocking serial I/O. Handlers
        # await work on it so the Tornado IOLoop never blocks on the serial bus.
        # None (e.g. in unit tests) falls back to the default thread pool, which
        # is fine for correctness -- only production needs the serialization
        # guarantee of a single worker.
        self.executor = executor # pylint: disable=attribute-defined-outside-init
        self.upload_path = os.path.join(os.path.dirname(__file__), 'upload') # pylint: disable=attribute-defined-outside-init

    async def run_blocking(self, func, *args, **kwargs):
        # Run a blocking (serial) call off the IOLoop thread and await its result.
        loop = IOLoop.current()
        return await loop.run_in_executor(self.executor, functools.partial(func, *args, **kwargs))

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET')
        self.set_header('Content-Type', 'application/json')

    # Helper function to send response
    def send_response(self, status, message='', data=None, status_code=200):
        resp = {'status': status, 'message': message, 'data': data}
        self.set_status(status_code)
        self.write(resp)
        self.finish()

    def prepare(self):
        if self.auth == 'admin':
            if not self.config.validate_admin_key(self.get_argument('admin_key', None)):
                logger.error("Invalid or missing admin key")
                self._deny(401, 'Invalid or missing API key.')
        elif self.auth is not None:
            key = self.get_argument('key', None)
            if not self.config.is_valid_api_key(key):
                self._deny(401, 'Unauthorized')
            if self.auth == 'dial' and not self.config.api_key_has_access_to_dial(key, self.path_args[0]):
                self._deny(403, 'API key does not have access to this dial.')

    def _deny(self, status_code, message):
        self.send_response(status='fail', message=message, status_code=status_code)
        raise Finish()

    @staticmethod
    def _arg_is_true(value):
        # Query arguments come back as strings (or the supplied default), never
        # as the bool singleton `True`, so a plain `value is True` check can
        # never match a request like `?force=true`.
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')

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
    auth = 'dial'

    def get(self, dial_uid):
        logger.debug(f"Request:STATUS - Device:{dial_uid}")

        dial = self.handler.get_dial_info(dial_uid=dial_uid)
        if dial is not None:
            return self.send_response(status='ok', data={field: dial[field] for field in STATUS_FIELDS})
        return self.send_response(status='fail', message='Invalid dial_uid or device is offline.')

class Device_Set_Handler(BaseHandler):
    auth = 'dial'

    def get(self, dial_uid):
        value = self.get_argument('value', 0)
        logger.debug(f"Request:SET - Device:{dial_uid} To:{value}")

        if self.handler.dial_set_percent(dial_uid=dial_uid, value=value):
            return self.send_response(status='ok', message='Update queued')
        return self.send_response(status='fail', message='Invalid dial_uid or device is offline.')

class Device_SetRaw_Handler(BaseHandler):
    auth = 'dial'

    async def get(self, dial_uid):
        value = self.get_argument('value', 0)
        logger.debug(f"Request:SET_RAW - Device:{dial_uid} To:{value}")

        if await self.run_blocking(self.handler.dial_set_raw, dial_uid=dial_uid, value=value):
            return self.send_response(status='ok', message='Dial RAW value updated', status_code=201)
        return self.send_response(status='fail', message='Invalid dial_uid or device is offline.', status_code=503)

class Device_Backlight_Handler(BaseHandler):
    auth = 'dial'

    def get(self, dial_uid):
        red = self.get_argument('red', 0)
        green = self.get_argument('green', 0)
        blue = self.get_argument('blue', 0)
        white = self.get_argument('white', 0)

        logger.debug(f"Request:BACKLIGHT - Device:{dial_uid} To: (red:{red} green:{green} blue:{blue} white:{white})")

        if self.handler.dial_set_backlight(dial_uid=dial_uid, red=red, green=green, blue=blue, white=white):
            return self.send_response(status='ok', message='Update queued', status_code=201)
        return self.send_response(status='fail', message='Invalid dial_uid or device is offline.', status_code=503)

class Device_Set_Image(BaseHandler):
    auth = 'dial'

    def post(self, dial_uid):
        get_force = self.get_argument('force', False)

        force_img_update = self._arg_is_true(get_force)

        logger.debug(f"Request:SET_IMAGE - Device:{dial_uid}")

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
    auth = 'dial'

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
    auth = 'dial'

    def get(self, gaugeUID):
        logger.debug("Request: GET_IMAGE_CRC")

        img_file = os.path.join(os.path.dirname(__file__), 'upload', f'img_{gaugeUID}')

        crc = self.get_file_crc(img_file)
        return self.send_response(status='ok', data=crc)

class Dial_Get_List(BaseHandler):
    auth = 'key'

    def get(self):
        logger.debug("Request: DEVICE_LIST")
        key = self.get_argument('key')
        dial_data = [
            {
                'uid': uid,
                'dial_name': dial['dial_name'],
                'value': dial['value'],
                'backlight': {c: v for c, v in dial['backlight'].items() if c != 'white'},
                'image_file': dial['image_file'],
            }
            for uid, dial in self.handler.get_dial_info().items()
            if self.config.api_key_has_access_to_dial(key, uid)
        ]
        return self.send_response(status='ok', data=dial_data)


class Dial_Provision(BaseHandler):
    auth = 'admin'

    async def get(self):

        logger.debug("Request: PROVISION_NEW_DIALS")

        dials = await self.run_blocking(self.handler.provision_dials)
        logger.debug(dials)

        return self.send_response(status='ok', data=dials)

class Dial_Reset_All(BaseHandler):
    auth = 'admin'

    async def get(self):

        logger.debug("Request: RESET_ALL_DEVICES")

        if await self.run_blocking(self.handler.reset_all_devices):
            return self.send_response(status='ok', message='All devices reset.', status_code=200)
        return self.send_response(status='fail', message='Failed to reset devices.', status_code=503)

class Dial_Reset_Device(BaseHandler):
    auth = 'dial'

    def get(self, gaugeUID):

        logger.debug(f"Request: RESET_DEVICE - Device:{gaugeUID}")

        if self.handler.reset_device(gaugeUID):
            return self.send_response(status='ok', message='Device reset.', status_code=200)
        return self.send_response(status='fail', message='Invalid dial_uid or device is offline.', status_code=503)

class Dial_Set_Dial_Name(BaseHandler):
    auth = 'dial'

    def get(self, gaugeUID):
        new_name = self.get_argument('name', None)
        logger.debug(f"Request:SET_NAME - Device:{gaugeUID} To: friendly name={new_name}")

        if new_name is None:
            return self.send_response(status='fail', message='Missing `name` parameter.', status_code=400)
        if len(new_name) < 3:
            return self.send_response(status='fail', message='Dial name should be at least 3 characters long.', status_code=400)
        if len(new_name) > 30:
            return self.send_response(status='fail', message='Dial name should be 30 characters or less.', status_code=400)
        if not re.fullmatch(r"[A-Za-z0-9_ -]*", new_name):
            return self.send_response(status='fail', message='Invalid characters! Only `A-Z`, `0-9`, `-`, `_` and space allowed.', status_code=400)

        if self.handler.dial_set_name(gaugeUID, new_name):
            return self.send_response(status='ok', status_code=201)
        return self.send_response(status='fail', message='Can not update dial name! Dial does not exist?', status_code=406)

class Dial_Reload_Device_Info(BaseHandler):
    auth = 'dial'

    async def get(self, gaugeUID):

        logger.debug(f"Request:GET_INFO - Device:{gaugeUID}")

        dial_info = await self.run_blocking(self.handler.dial_reload_info_from_hardware, gaugeUID)
        return self.send_response(status='ok', data=dial_info)

class Dial_Set_Calibration(BaseHandler):
    auth = 'dial'

    async def get(self, gaugeUID):
        dac_calibration = self.get_argument('value', None)
        logger.debug(f"Request:SET_CALIBRATION - Device:{gaugeUID} To: value={dac_calibration}")

        if dac_calibration is None:
            return self.send_response(status='fail', message='Missing `value` parameter.', status_code=400)
        if await self.run_blocking(self.handler.dial_set_calibration, dial_uid=gaugeUID, value=dac_calibration, fullScale=False):
            return self.send_response(status='ok', message="Calibration value updated", status_code=201)
        return self.send_response(status='fail', message='Invalid dial_uid or device is offline.', status_code=503)

class Dial_Set_Easing(BaseHandler):
    auth = 'dial'

    async def get(self, gaugeUID, target):
        step = self.get_argument('step', None)
        period = self.get_argument('period', None)
        logger.debug(f"Request:SET_EASING_{target.upper()} - Device:{gaugeUID} Step:{step} Period:{period}")

        if step is None and period is None:
            return self.send_response(status='fail', message="Please provide at least one of required parameters (`step` or `period`)", status_code=400)

        try:
            step = None if step is None else int(step)
            period = None if period is None else int(period)
        except (TypeError, ValueError):
            return self.send_response(status='fail', message="`step` and `period` must be integers.", status_code=400)

        if await self.run_blocking(self.handler.dial_set_easing, gaugeUID, target, step=step, period=period):
            return self.send_response(status='ok')
        return self.send_response(status='fail', message="Device not present", status_code=406)

# -- Keys --
class Admin_Keys_List(BaseHandler):
    auth = 'admin'

    def get(self):
        logger.debug("Request:Admin_Keys_List")
        return self.send_response(status='ok', data=list(self.config.list_keys().values()))

class Admin_Keys_Create(BaseHandler):
    auth = 'admin'

    def post(self):
        logger.debug("Request:Admin_Keys_Create")
        # `priviledges` is ignored; only the configured master key is admin.
        new_key = self.config.create_api_key(self.get_argument('name', 'Not set'))
        dial_access = self.get_argument('dials', None)
        if dial_access:
            self.config.api_key_add_dial_access(new_key, dial_access.split(';'))
        return self.send_response(status='ok', data=new_key)

class Admin_Keys_Update(BaseHandler):
    auth = 'admin'

    def post(self):
        logger.debug("Request:Admin_Keys_Update")
        key = self.get_argument('key', None)
        name = self.get_argument('name', None)
        dial_list = self.get_argument('dials', None)

        if not self.config.is_valid_api_key(key):
            return self.send_response(status='fail', message='Invalid key selected!')
        if name is not None and not self.config.update_api_key(key_uid=key, key_name=name):
            return self.send_response(status='fail', message='Failed to update key!')

        dials_updated = bool(dial_list) and self.config.api_key_add_dial_access(key, dial_list.split(';'))
        if name is not None or dials_updated:
            return self.send_response(status='ok', message='Key updated!')
        return self.send_response(status='fail', message='Failed to update key!')

class Admin_Keys_Remove(BaseHandler):
    auth = 'admin'

    def get(self):
        logger.debug("Request:Admin_Keys_Remove")
        key_uid = self.get_argument('key', None)

        if not self.config.is_valid_api_key(key_uid):
            return self.send_response(status='fail', message='Invalid key selected!')
        if not self.config.delete_api_key(key_uid):
            return self.send_response(status='fail', message='Failed to remove key!')
        return self.send_response(status='ok', message='Key removed!')

# -- Default 404 --
class Default_404_Handler(RequestHandler):
    # Override prepare() instead of get() to cover all possible HTTP methods.
    def prepare(self):
        self.set_status(404)
        resp = {'status': 'fail', 'message': 'Not found'}
        self.write(resp)
        raise Finish()


def make_routes(handlers_config):
    """Return the API routes, a JSON 404 for other /api/ paths, and the Web UI."""
    return [
        (r"/api/v0/dial/provision", Dial_Provision, handlers_config),
        (r"/api/v0/dial/reset_all", Dial_Reset_All, handlers_config),
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
        (r"/api/v0/dial/([0-9A-F]*?)/reset", Dial_Reset_Device, handlers_config),
        (r"/api/v0/dial/([0-9A-F]*?)/calibrate", Dial_Set_Calibration, handlers_config),
        (r"/api/v0/dial/([0-9A-F]*?)/easing/(dial|backlight)", Dial_Set_Easing, handlers_config),
        (r"/api/v0/admin/keys/list", Admin_Keys_List, handlers_config),
        (r"/api/v0/admin/keys/create", Admin_Keys_Create, handlers_config),
        (r"/api/v0/admin/keys/remove", Admin_Keys_Remove, handlers_config),
        (r"/api/v0/admin/keys/update", Admin_Keys_Update, handlers_config),
        (r"/api/.*", Default_404_Handler),
        (r"/(.*)", StaticFileHandler, {'path': WEB_ROOT, 'default_filename': 'index.html'}),
    ]


class Dial_API_Service:
    def __init__(self):
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

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
                notify('error', "Hub not found", "Could not find VU1 Hub on the USB bus.\r\n"\
                       "Please make sure it is plugged in and (if necessary) drivers are installed.\r\n"\
                       "Then restart the VU Server application.\r\nVU server application will close now.")
                sys.exit(1)

        logger.info("VU1 HUB port: {}".format(self.serialPort))
        self.dial_driver = DialSerialDriver(self.serialPort)
        self.dial_handler = ServerDialHandler(self.dial_driver, self.config)

        # All blocking serial I/O (request handlers *and* the periodic updater)
        # runs on this single dedicated worker thread. One worker keeps serial
        # access serialized -- so the periodic loop and an offloaded handler
        # never talk to the bus at once -- while keeping the Tornado IOLoop free
        # to serve other requests instead of freezing on the serial port.
        self.serial_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='serial')

        # If we don't see any dials, try looking/provisioning some. Only do this
        # when the bus is genuinely empty -- the old `<= 1` check re-ran the
        # provisioning scan on every startup whenever a single dial was present.
        if len(self.dial_handler.dials) == 0:
            logger.info("No dials found. Searching the bus for new ones...")
            self.dial_handler.provision_dials(num_attempts=3)

        handlers_config = { "handler":self.dial_handler, "config":self.config, "executor":self.serial_executor }
        self.handlers = make_routes(handlers_config)

    def signal_handler(self, signal, frame):
        print('\r\nYou pressed Ctrl+C!')

        def do_shutdown():
            self.shut_down_dials()
            self.shutdown_server()
        IOLoop.current().add_callback_from_signal(do_shutdown)

    def shut_down_dials(self):
        print("Shutting down dials...")
        try:
            for dial in self.dial_driver.dials:
                logger.debug(f"Shutting down dial {dial}")
                self.dial_driver.dial_single_set_percent(dial, 0)
                self.dial_driver.dial_set_backlight(device=dial, red=0, green=0, blue=0, white=0)

        except Exception as e:
            logger.error("Failed to gracefully shut down dials")
            logger.error(f"Error: {e}")

    def shutdown_server(self):
        logger.info('Stopping API server')
        logger.info('Will shutdown in 3 seconds ...')
        io_loop = IOLoop.instance()

        def stop_loop():
            io_loop.stop()
            logger.info('Shutdown')
        io_loop.call_later(3, stop_loop)

    def run_forever(self):
        logger.info("Karanovic Research Dials - Starting API server")
        app = Application(self.handlers)

        server_config = self.config.get_server_config()
        port = server_config['port']
        # An empty hostname binds all interfaces.
        hostname = server_config['hostname']
        logger.info(f"VU1 API server is listening on http://{hostname or '0.0.0.0'}:{port}")
        app.listen(port, address=hostname)

        logger.info(f"Provide master key '{server_config['master_key']}' to your main application")
        logger.info("to allow it to manage this server and the VU dials.")

        # Run the periodic dial update on the serial worker thread so its
        # blocking serial writes (value/backlight/image, incl. chunked image
        # sends with their inter-chunk sleeps) never freeze the IOLoop.
        async def periodic_dial_update():
            await IOLoop.current().run_in_executor(self.serial_executor,
                                                   self.dial_handler.periodic_dial_update)

        pc = PeriodicCallback(periodic_dial_update, server_config['dial_update_period'])
        pc.start()

        IOLoop.instance().start()


def main(cmd_args=None):
    configure_logging(cmd_args.logging if cmd_args else 'info')
    exit_code = 0
    try:
        Dial_API_Service().run_forever()
    except SerialException:
        logger.exception("VU Dials API service - Serial port access denied")
        notify('warning', "Serial Port Access Denied", "VU Server failed to start. Access to serial port denied.\r\nVU Server already running?")
        exit_code = 1
    except Exception:
        logger.exception("VU Dials API service crashed.")
        notify('error', "Crashed", "VU Server has crashed unexpectedly!\r\nPlease check log files for more information.")
        exit_code = 1
    os._exit(exit_code)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Karanovic Research - VU Dials API service')
    parser.add_argument('-l', '--logging', type=str.lower, choices=['debug', 'info'], default='info',
                        help='Set logging level. Default is `info`')
    args = parser.parse_args()
    main(args)
