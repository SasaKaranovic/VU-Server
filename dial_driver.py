import time
import textwrap
from PIL import Image
from dials.Comms_Hub_Server import hub_commands, hub_data_types, hub_status_codes
from dials.base_logger import logger
from serial_driver import SerialHardware, DEFAULT_READ_TIMEOUT, find_port


class DialSerialDriver(SerialHardware):
    # A backlight write is ACKed at once, not after the easing animation, so a
    # short read window keeps a silent dial from blocking each retry for 5s.
    BACKLIGHT_READ_TIMEOUT = 0.5

    # A percent-set is ACKed just as promptly (15-19ms on the wire).
    DIAL_SET_READ_TIMEOUT = 0.5

    IMAGE_CHUNK_SIZE = 1000

    def __init__(self, port_info):
        super().__init__(port_info, timeout=2)
        self.dials = {}  # bus index -> UID, from the last rescan

    def _sendCommand(self, cmd, dataType, *data, read_timeout=DEFAULT_READ_TIMEOUT):
        """
        Frame and send one hub command, then parse its reply.

        @param data byte values; ints or numeric strings, each 0-255
        @returns the reply payload str, or a bool for a status reply or no reply
        """
        body = bytes(int(elem) for elem in data).hex().upper()
        payload = f">{cmd:02X}{dataType:02X}{len(body) // 2:04X}{body}"
        logger.debug(f"Sending `{payload}`")
        response = self.serial_transaction(payload, read_timeout=read_timeout)
        return self._parseResponse(response, expected_cmd=cmd)

    def _send_cmd_with_uin32(self, dialID, cmd, value, dt=hub_data_types.COMM_DATA_SINGLE_VALUE):
        return self._sendCommand(cmd, dt, dialID, *(value & 0xFFFFFFFF).to_bytes(4, 'big'))

    @staticmethod
    def _hex(field):
        """Parse a hex field off the wire; None when malformed."""
        try:
            return int(field, 16)
        except ValueError:
            return None

    def _parseResponse(self, response, expected_cmd):
        """
        Pull this command's reply out of the received lines.

        The hub echoes the command byte, so a reply carrying another command
        answers something else and is skipped.
        """
        for line in response:
            if not line.startswith('<'):
                continue

            if self._hex(line[1:3]) != expected_cmd:
                logger.error(f"_parseResponse: ignoring reply {line!r} while awaiting 0x{expected_cmd:02X}")
                continue

            logger.debug(f"_parseResponse: matched {line!r}")
            data = line[9:]
            if self._hex(line[3:5]) != hub_data_types.COMM_DATA_STATUS_CODE:
                return data
            status = self._hex(data)
            if status == hub_status_codes.GAUGE_STATUS_OK:
                return True
            logger.error(f"Hub returned status {data!r} for command 0x{expected_cmd:02X}")
            return False
        return False

    @staticmethod
    def _hex_decode(payload, text):
        """Decode a hex payload to str when text is set, else to bytes; empty on a missing or malformed payload."""
        empty = '' if text else b''
        if not payload or not isinstance(payload, str):
            logger.error(f"Expected a hex payload, got {payload!r}")
            return empty
        try:
            raw = bytes.fromhex(payload)
            return raw.decode() if text else raw
        except ValueError as e:
            logger.error(f"Malformed hex payload {payload!r}: {e}")
            return empty

    def bus_rescan(self):
        logger.debug("@bus_rescan")
        return self._sendCommand(hub_commands.COMM_CMD_RESCAN_BUS, hub_data_types.COMM_DATA_NONE)

    def get_dial_list(self, rescan=False):
        """@returns {bus index: UID} for the dials found by the last rescan."""
        logger.debug(f"@get_dial_list(rescan={rescan})")
        if rescan:
            self.bus_rescan()
            resp = self._sendCommand(hub_commands.COMM_CMD_GET_DEVICES_MAP, hub_data_types.COMM_DATA_NONE)
            if not resp:
                logger.error("Invalid response received from COMM_CMD_GET_DEVICES_MAP")
                logger.error(resp)
                return {}

            onlineDials = [key for key, elem in enumerate(textwrap.wrap(resp, 2)) if int(elem, 16) == 1]
            # Rebuild the map from scratch so dials that dropped off the bus
            # since the last scan don't linger as phantom entries.
            self.dials = {dialIndex: self.dial_get_uid(dialIndex) for dialIndex in onlineDials}

        return dict(self.dials)

    def set_all_dials_to(self, value):
        logger.debug(f"@set_all_dials_to(value={value})")
        self.dial_multiple_set_percent(list(self.dials), [value] * len(self.dials))

    def dial_get_uid(self, dialIndex):
        logger.debug(f"@dial_get_uid(dialIndex={dialIndex})")
        return self._sendCommand(hub_commands.COMM_CMD_GET_DEVICE_UID, hub_data_types.COMM_DATA_SINGLE_VALUE, dialIndex)

    def _get_info_str(self, cmd, dialIndex):
        return self._hex_decode(self._sendCommand(cmd, hub_data_types.COMM_DATA_SINGLE_VALUE, dialIndex), text=True)

    def dial_get_fw_hash(self, dialIndex):
        return self._get_info_str(hub_commands.COMM_CMD_GET_BUILD_INFO, dialIndex)

    def dial_get_fw_version(self, dialIndex):
        return self._get_info_str(hub_commands.COMM_CMD_GET_FW_INFO, dialIndex)

    def dial_get_hw_version(self, dialIndex):
        return self._get_info_str(hub_commands.COMM_CMD_GET_HW_INFO, dialIndex)

    def dial_get_protocol_version(self, dialIndex):
        return self._get_info_str(hub_commands.COMM_CMD_GET_PROTOCOL_INFO, dialIndex)

    def dial_calibrate(self, dialID, value, fullScale=True):
        logger.debug(f"@dial_calibrate(dialID={dialID}, value={value}, fullScale={fullScale})")
        if fullScale:
            cmd = hub_commands.COMM_CMD_SET_DIAL_CALIBRATE_MAX
        else:
            cmd = hub_commands.COMM_CMD_SET_DIAL_CALIBRATE_HALF

        return self._send_cmd_with_uin32(dialID, cmd, value, dt=hub_data_types.COMM_DATA_KEY_VALUE_PAIR)

    def dial_easing_dial_step(self, dialID, value):
        logger.debug(f"@dial_easing_dial_step(dialID={dialID}, value={value})")
        return self._send_cmd_with_uin32(dialID, hub_commands.COMM_CMD_SET_DIAL_EASING_STEP, value)

    def dial_easing_dial_period(self, dialID, value):
        logger.debug(f"@dial_easing_dial_period(dialID={dialID}, value={value})")
        return self._send_cmd_with_uin32(dialID, hub_commands.COMM_CMD_SET_DIAL_EASING_PERIOD, value)

    def dial_easing_backlight_step(self, dialID, value):
        logger.debug(f"@dial_easing_backlight_step(dialID={dialID}, value={value})")
        return self._send_cmd_with_uin32(dialID, hub_commands.COMM_CMD_SET_BACKLIGHT_EASING_STEP, value)

    def dial_easing_backlight_period(self, dialID, value):
        logger.debug(f"@dial_easing_backlight_period(dialID={dialID}, value={value})")
        return self._send_cmd_with_uin32(dialID, hub_commands.COMM_CMD_SET_BACKLIGHT_EASING_PERIOD, value)

    def dial_easing_get_config(self, dialID):
        logger.debug(f"@dial_easing_get_config(dialID={dialID})")
        keys = ('dial_step', 'dial_period', 'backlight_step', 'backlight_period')
        ret = self._sendCommand(hub_commands.COMM_CMD_GET_EASING_CONFIG, hub_data_types.COMM_DATA_SINGLE_VALUE, dialID)
        ret = self._hex_decode(ret, text=False)

        if len(ret) < 16:
            logger.error(f"dial_easing_get_config: expected 16 bytes, got {len(ret)} for dial {dialID}")
            return dict.fromkeys(keys, 0)

        return {key: int.from_bytes(ret[4*i:4*i+4], 'big') for i, key in enumerate(keys)}

    def dial_single_set_raw(self, dialID, value):
        logger.debug(f"@dial_single_set_raw(dialID={dialID}, value={value})")
        return self._sendCommand(hub_commands.COMM_CMD_SET_DIAL_RAW_SINGLE, hub_data_types.COMM_DATA_KEY_VALUE_PAIR, dialID, (value>>8)&0xFF, value&0xFF)

    def dial_single_set_percent(self, dialID, value):
        logger.debug(f"@dial_single_set_percent(dialID={dialID}, value={value})")
        # The hub ACKs a percent-set; an unread ACK would be taken as the next command's reply.
        return self._sendCommand(hub_commands.COMM_CMD_SET_DIAL_PERC_SINGLE, hub_data_types.COMM_DATA_KEY_VALUE_PAIR, dialID, value&0xFF, read_timeout=self.DIAL_SET_READ_TIMEOUT)

    def dial_multiple_set_percent(self, devices, values):
        logger.debug(f"@dial_multiple_set_percent(devices={devices}, values={values})")
        if len(devices) != len(values):
            logger.error("Number of devices does not match number of values")
            return False

        data = []
        for device, value in zip(devices, values):
            data += [device, value]

        return self._sendCommand(hub_commands.COMM_CMD_SET_DIAL_PERC_MULTIPLE, hub_data_types.COMM_DATA_KEY_VALUE_PAIR, *data)

    def dial_display_clear(self, device, whiteBackground=True):
        logger.debug(f"@dial_display_clear(device={device}, whiteBackground={whiteBackground})")
        return self._sendCommand(hub_commands.COMM_CMD_DISPLAY_CLEAR, hub_data_types.COMM_DATA_SINGLE_VALUE, device, 0 if whiteBackground else 1)

    def dial_display_goto_xy(self, device, x, y):
        logger.debug(f"@dial_display_goto_xy(device={device}, x={x}, y={y})")
        return self._sendCommand(hub_commands.COMM_CMD_DISPLAY_GOTO_XY, hub_data_types.COMM_DATA_SINGLE_VALUE, device, (x>>8)&0xFF, x&0xFF, (y>>8)&0xFF, y&0xFF)

    def display_send_image(self, device, img_filepath):
        """Send an image file's pixels to the display buffer; False if the file cannot be converted or a chunk fails."""
        logger.debug(f"@display_send_image(device={device}, img_filepath={img_filepath})")
        img_data = self.img_to_binary(img_filepath)
        if img_data is None:
            return False
        return self.display_send_image_data(device, img_data)

    def display_send_image_data(self, device, imageData):
        logger.debug(f"@display_send_image_data(device={device}, {len(imageData)} bytes)")
        if not imageData:
            logger.error("Invalid image buffer size!")
            return False

        start_time = time.monotonic()
        for start in range(0, len(imageData), self.IMAGE_CHUNK_SIZE):
            chunk = imageData[start:start + self.IMAGE_CHUNK_SIZE]
            if not self._sendCommand(hub_commands.COMM_CMD_DISPLAY_IMG_DATA, hub_data_types.COMM_DATA_SINGLE_VALUE, device, *chunk):
                return False
            time.sleep(0.2)
        logger.debug(f"Send image data took {time.monotonic() - start_time:.3f}s")
        return True

    @staticmethod
    def img_to_binary(img_filepath):
        """
        Pack an image as 1-bit columns, 8 vertical pixels per byte with the top pixel in the MSB.

        @returns the packed bytes, or None if the file cannot be read as an image
        """
        try:
            with Image.open(img_filepath) as img:
                columns = img.convert("L").point(lambda p: 255 if p > 127 else 0, "1").transpose(Image.Transpose.TRANSPOSE)
        except Exception as e:
            logger.error(f"Cannot convert image '{img_filepath}': {e}")
            return None

        data = bytearray(columns.tobytes())
        # A partial last byte in each column carries its bits in the low end, not padded at the high end.
        height = columns.width
        if height % 8:
            stride = -(-height // 8)
            data[stride-1::stride] = bytes(b >> (8 - height % 8) for b in data[stride-1::stride])
        return bytes(data)

    def update_display(self, device, imageData=None, imageFile=None):
        """Clear the display, send the image, and show it; False if the image could not be sent."""
        logger.debug(f"@update_display(device={device})")
        device = int(device)

        self.dial_display_clear(device, True)
        self.dial_display_goto_xy(device, 0, 0)

        if imageData is not None:
            sent = self.display_send_image_data(device, imageData)
        elif imageFile is not None:
            sent = self.display_send_image(device, imageFile)
        else:
            raise ValueError("Image data and ImageFile can't both be none!")
        if not sent:
            return False
        return self.dial_display_show(device)

    def dial_display_show(self, device):
        logger.debug(f"@dial_display_show(device={device})")
        return self._sendCommand(hub_commands.COMM_CMD_DISPLAY_SHOW_IMG, hub_data_types.COMM_DATA_SINGLE_VALUE, device)

    def dial_set_backlight(self, device, red, green, blue, white):
        logger.debug(f"@dial_set_backlight(device={device}, red={red}, green={green}, blue={blue}, white={white})")
        device = int(device)
        if device not in self.dials:
            logger.error(f"dial_set_backlight: unknown device {device!r}")
            return False
        return self._sendCommand(hub_commands.COMM_CMD_SET_RGB_BACKLIGHT, hub_data_types.COMM_DATA_MULTIPLE_VALUE, device, red, green, blue, white, read_timeout=self.BACKLIGHT_READ_TIMEOUT)

    def provision_dials(self):
        logger.debug("@provision_dials")
        return self._sendCommand(hub_commands.COMM_CMD_PROVISION_DEVICE, hub_data_types.COMM_DATA_NONE)

    def reset_all_devices(self):
        logger.debug("@reset_all_devices")
        return self._sendCommand(hub_commands.COMM_CMD_RESET_ALL_DEVICES, hub_data_types.COMM_DATA_NONE)

    @staticmethod
    def find_gauge_hub():
        logger.debug("Searching for COM port with VID:1027 and PID:24597")
        return find_port(lambda p: (p.vid, p.pid) == (1027, 24597))
