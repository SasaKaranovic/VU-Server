import os
import time
import textwrap
import math
from datetime import timedelta
from io import BytesIO
import numpy as np
from PIL import Image
from serial.tools.list_ports import comports
from dials.Comms_Hub_Server import hub_config, hub_commands, hub_data_types, hub_status_codes
from dials.base_logger import logger
from serial_driver import SerialHardware


class DialSerialDriver(SerialHardware):
    dials = {}
    hub_info = {}

    def __init__(self, port_info):
        super(DialSerialDriver, self).__init__(port_info, timeout=2)

        self.commands = hub_commands()
        self.hub_config = hub_config()
        self.data_type = hub_data_types()
        self.status_codes = hub_status_codes()

    def _get_max_packet_size(self):
        max_size = math.floor( (self.hub_config.GAUGE_COMM_MAX_RX_DATA_LEN - (self.hub_config.GAUGE_COMM_HEADER_LEN*2) )/2)
        return max_size

    def _sendCommand(self, cmd, dataType, dataLen=0, data=None):
        if dataLen == 0:
            payload = ">{:02X}{:02X}{:04X}".format(cmd, dataType, dataLen)
        elif dataLen == 1:
            if data < 256:
                payload = ">{:02X}{:02X}{:04X}{:02X}".format(cmd, dataType, dataLen, data)
            elif data >= 256:
                payload = ">{:02X}{:02X}{:04X}{:04X}".format(cmd, dataType, dataLen+1, data)
        elif dataLen > 1:
            formattedData = ""
            for elem in data:
                if isinstance(elem, str):
                    formattedData = formattedData + f"{int(elem):0{2 if int(elem) < 256 else 4}X}"
                elif isinstance(elem, int):
                    formattedData = formattedData + f"{elem:0{2 if elem < 256 else 4}X}"
                else:
                    raise ValueError('Unsupported data type ({})'.format(type(elem)))

            payload = ">{:02X}{:02X}{:04X}{}".format(cmd, dataType, int(len(formattedData)/2), formattedData)

        logger.debug(f"CMD:{cmd} - Type:{dataType} - Len:{dataLen}".format(payload))
        logger.debug("Sending `{}`".format(payload))
        response = self.serial_transaction(payload)
        return self._parseResponse(response)

    def _send_cmd_with_uin32(self, dialID, cmd, value, dt=None):
        if dt is None:
            dt = self.data_type.COMM_DATA_SINGLE_VALUE
        data = [dialID, ((value>>24)&0xFF), ((value>>16)&0xFF), ((value>>8)&0xFF), (value&0xFF)]
        return self._sendCommand(cmd, dt, len(data), data)

    def _parseResponse(self, response):
        for line in response:
            logger.debug(line)
            if line.startswith('<'):
                cmd = line[1:3]
                dataType = line[3:5]
                dataLen = line[5:9]
                data = line[9:]
                ret = {'cmd':cmd, 'dataType':dataType, 'dataLen':dataLen, 'data':data}

                if dataType == self.data_type.COMM_DATA_STATUS_CODE:
                    return self._checkStatus(ret['data'])
                return ret['data']
        return False

    def _checkStatus(self, statusCode):
        if int(statusCode, 16) == self.status_codes.GAUGE_STATUS_OK:
            return True
        logger.error("Error code: {}".format(int(statusCode, 16)))
        return False

    def _convert_hex_str_to_str(self, hex_string):
        if not hex_string:
            logger.error(f"Empty hex string received {hex_string}")
            return ''

        if len(hex_string)%2:
            logger.error(f"Hex string should be divisible by 2! (len={len(hex_string)})")
            return ''

        try:
            byte_array = bytearray.fromhex(hex_string)
            hex_string = byte_array.decode()
            return hex_string
        except Exception as e:
            logger.error(e)
            return ''

    def _convert_hex_str_to_byte_array(self, hex_string):
        if not hex_string:
            logger.error(f"Empty hex string received {hex_string}")
            return bytes()

        if len(hex_string)%2:
            logger.error(f"Hex string should be divisible by 2! (len={len(hex_string)})")
            return bytes()

        try:
            byte_array = bytearray.fromhex(hex_string)
            return byte_array
        except Exception as e:
            logger.error(e)
            return bytes()

    def bus_rescan(self):
        logger.debug("@bus_rescan")
        return self._sendCommand(self.commands.COMM_CMD_RESCAN_BUS, self.data_type.COMM_DATA_NONE)

    def get_dial_list(self, rescan=False):
        logger.debug(f"@get_dial_list(rescan={rescan})")
        if rescan:
            resp = self.bus_rescan()
            resp = self._sendCommand(self.commands.COMM_CMD_GET_DEVICES_MAP, self.data_type.COMM_DATA_NONE)
            if not resp:
                logger.error("Invalid response received from COMM_CMD_GET_DEVICES_MAP")
                logger.error(resp)
                return []

            resp = textwrap.wrap(resp, 2)
            onlineDials = []
            for key, elem in enumerate(resp):
                if int(elem, 16) == 1:
                    onlineDials.append(key)

            for dialIndex in onlineDials:
                deviceUID = self.dial_get_uid(dialIndex)                # Read dial UID
                # Friendly name will be added from config
                self.dials[dialIndex] = {
                                            'index': str(dialIndex),
                                            'uid': deviceUID,
                                            'dial_name': 'Not set',
                                            'value': 0,
                                            'rgbw': [0, 0, 0, 0],
                                            'easing': {
                                                'dial_step': '?',
                                                'dial_period': '?',
                                                'backlight_step': '?',
                                                'backlight_period': '?',
                                            },
                                            'fw_hash': '?',
                                            'fw_version': '?',
                                            'hw_version': '?',
                                            'protocol_version': '?',
                                        }

        dialList = []
        for key, val in self.dials.items():
            dialList.append(val)

        return dialList

    def set_all_dials_to(self, value):
        logger.debug(f"@set_all_dials_to(value={value})")
        dials = []
        values = []

        for dial in self.dials:
            dials.append(dial)
            values.append(value)
            self.dials[dial]['value'] = 0

        self.dial_multiple_set_percent(dials, values)


    def get_dial(self, dialID=None, UID=None):
        if dialID is None and UID is None:
            logger.error("Both dial ID and UID can't be none!")
            return {}

        if dialID is None:
            dialID = self._findDial(UID)

        if dialID is None:
            logger.error("Dial with UID `{}` is not present.".format(UID))
            return None

        return self.dials[dialID]

    def set_dial(self, dialID=None, UID=None, value=None, sendCMD=True):
        if dialID is None and UID is None:
            logger.error("Both dial ID and UID can't be none!")
            return {}

        if dialID is None:
            dialID = self._findDial(UID)

        if dialID is None:
            logger.error("Dial with UID `{}` is not present.".format(UID))
            return False

        if sendCMD:
            self.dial_single_set_percent(dialID, int(value))
        return True

    def _findDial(self, UID):
        for entry in self.dials:
            if self.dials[entry]['uid'] == UID:
                return entry
        return None

    def _verify_device(self, device):
        if isinstance(device, str):
            if len(device) <= 3:
                return int(device)
            device = self._findDial(device)

            if device is None:
                logger.error(f"Can not find dial '{device}'")
            return device

        elif isinstance(device, int):
            return device

        else:
            raise ValueError(f"Unexpected device type type(device)='{type(device)}'")

    def dial_get_uid(self, dialIndex):
        logger.debug(f"@dial_get_uid(dialIndex={dialIndex})")
        return self._sendCommand(self.commands.COMM_CMD_GET_DEVICE_UID, self.data_type.COMM_DATA_SINGLE_VALUE, 1, dialIndex)

    def dial_get_fw_hash(self, dialIndex):
        logger.debug(f"@dial_get_fw_hash(dialIndex={dialIndex})")
        cmd = self.commands.COMM_CMD_GET_BUILD_INFO
        data = dialIndex
        ret = self._sendCommand(cmd, self.data_type.COMM_DATA_SINGLE_VALUE, 1, data)
        return self._convert_hex_str_to_str(ret)

    def dial_get_fw_version(self, dialIndex):
        logger.debug(f"@dial_get_fw_version(dialIndex={dialIndex})")
        cmd = self.commands.COMM_CMD_GET_FW_INFO
        data = dialIndex
        ret = self._sendCommand(cmd, self.data_type.COMM_DATA_SINGLE_VALUE, 1, data)
        return self._convert_hex_str_to_str(ret)

    def dial_get_hw_version(self, dialIndex):
        logger.debug(f"@dial_get_hw_version(dialIndex={dialIndex})")
        cmd = self.commands.COMM_CMD_GET_HW_INFO
        data = dialIndex
        ret = self._sendCommand(cmd, self.data_type.COMM_DATA_SINGLE_VALUE, 1, data)
        return self._convert_hex_str_to_str(ret)

    def dial_get_protocol_version(self, dialIndex):
        logger.debug(f"@dial_get_hw_version(dialIndex={dialIndex})")
        cmd = self.commands.COMM_CMD_GET_PROTOCOL_INFO
        data = dialIndex
        ret = self._sendCommand(cmd, self.data_type.COMM_DATA_SINGLE_VALUE, 1, data)
        return self._convert_hex_str_to_str(ret)

    def set_dial_power(self, powerOn=True):
        logger.debug(f"@set_dial_power(powerOn={powerOn})")
        data = 0
        if powerOn is True:
            data = 1
        return self._sendCommand(self.commands.COMM_CMD_DIAL_POWER, self.data_type.COMM_DATA_SINGLE_VALUE, 1, data)

    def dial_calibrate(self, dialID, value, fullScale=True):
        logger.debug(f"@dial_calibrate(dialID={dialID}, value={value}, fullScale={fullScale})")
        if fullScale:
            cmd = self.commands.COMM_CMD_SET_DIAL_CALIBRATE_MAX
        else:
            cmd = self.commands.COMM_CMD_SET_DIAL_CALIBRATE_HALF

        return self._send_cmd_with_uin32(dialID, cmd, value, dt=self.data_type.COMM_DATA_KEY_VALUE_PAIR)

    def dial_easing_dial_step(self, dialID, value):
        logger.debug(f"@dial_easing_dial_step(dialID={dialID}, value={value})")
        cmd = self.commands.COMM_CMD_SET_DIAL_EASING_STEP
        data = [dialID, ((value>>24)&0xFF), ((value>>16)&0xFF), ((value>>8)&0xFF), (value&0xFF)]
        return self._sendCommand(cmd, self.data_type.COMM_DATA_SINGLE_VALUE, len(data), data)

    def dial_easing_dial_period(self, dialID, value):
        logger.debug(f"@dial_easing_dial_period(dialID={dialID}, value={value})")
        cmd = self.commands.COMM_CMD_SET_DIAL_EASING_PERIOD
        data = [dialID, ((value>>24)&0xFF), ((value>>16)&0xFF), ((value>>8)&0xFF), (value&0xFF)]
        return self._sendCommand(cmd, self.data_type.COMM_DATA_SINGLE_VALUE, len(data), data)

    def dial_easing_backlight_step(self, dialID, value):
        logger.debug(f"@dial_easing_backlight_step(dialID={dialID}, value={value})")
        cmd = self.commands.COMM_CMD_SET_BACKLIGHT_EASING_STEP
        data = [dialID, ((value>>24)&0xFF), ((value>>16)&0xFF), ((value>>8)&0xFF), (value&0xFF)]
        return self._sendCommand(cmd, self.data_type.COMM_DATA_SINGLE_VALUE, len(data), data)

    def dial_easing_backlight_period(self, dialID, value):
        logger.debug(f"@dial_easing_backlight_period(dialID={dialID}, value={value})")
        cmd = self.commands.COMM_CMD_SET_BACKLIGHT_EASING_PERIOD
        data = [dialID, ((value>>24)&0xFF), ((value>>16)&0xFF), ((value>>8)&0xFF), (value&0xFF)]
        return self._sendCommand(cmd, self.data_type.COMM_DATA_SINGLE_VALUE, len(data), data)

    def dial_easing_get_config(self, dialID):
        easing = { 'dial_step':0, 'dial_period':0, 'backlight_step':0, 'backlight_period':0 }
        logger.debug(f"@dial_easing_get_config(dialID={dialID})")
        ret = self._sendCommand(self.commands.COMM_CMD_GET_EASING_CONFIG, self.data_type.COMM_DATA_NONE)
        ret = self._convert_hex_str_to_byte_array(ret)

        easing['dial_step']         = int(ret[0]) << 24 | int(ret[1]) << 16 | int(ret[2]) << 8 | int(ret[3])
        easing['dial_period']       = int(ret[4]) << 24 | int(ret[5]) << 16 | int(ret[6]) << 8 | int(ret[7])
        easing['backlight_step']    = int(ret[8]) << 24 | int(ret[9]) << 16 | int(ret[10]) << 8 | int(ret[11])
        easing['backlight_period']  = int(ret[12]) << 24 | int(ret[13]) << 16 | int(ret[14]) << 8 | int(ret[15])
        # logger.debug(f"@ret:{ret}")
        # logger.debug(f"@easing:{easing}")

        return easing

    def dial_single_set_raw(self, dialID, value):
        logger.debug(f"@dial_single_set_raw(dialID={dialID}, value={value})")
        data = [dialID, ((value>>8)&0xFF), (value&0xFF)]
        return self._sendCommand(self.commands.COMM_CMD_SET_DIAL_RAW_SINGLE, self.data_type.COMM_DATA_KEY_VALUE_PAIR, len(data), data)

    def dial_single_set_percent(self, dialID, value):
        logger.debug(f"@dial_single_set_percent(dialID={dialID}, value={value})")
        if self.dials.get(int(dialID), False):
            self.dials[int(dialID)]['value'] = value
        data = [dialID, (value&0xFF)]
        return self._sendCommand(self.commands.COMM_CMD_SET_DIAL_PERC_SINGLE, self.data_type.COMM_DATA_KEY_VALUE_PAIR, len(data), data)

    def dial_multiple_set_percent(self, devices, values):
        logger.debug(f"@dial_multiple_set_percent(devices={devices}, values={values})")
        if len(devices) != len(values):
            logger.error("Number of devices does not match number of values")
            return False

        data = []
        for i in range(len(devices)):
            self.set_dial(devices[i], values[i], sendCMD=False)
            data.append(devices[i])
            data.append(values[i])

        return self._sendCommand(self.commands.COMM_CMD_SET_DIAL_PERC_MULTIPLE, self.data_type.COMM_DATA_KEY_VALUE_PAIR, len(data), data)

    def dial_display_clear(self, device, whiteBackground=True):
        logger.debug(f"@dial_display_clear(device={device}, whiteBackground={whiteBackground})")
        if whiteBackground:
            data = [int(device), 0]
        else:
            data = [int(device), 1]
        return self._sendCommand(self.commands.COMM_CMD_DISPLAY_CLEAR, self.data_type.COMM_DATA_SINGLE_VALUE, len(data), data)

    def dial_display_goto_xy(self, device, x, y):
        logger.debug(f"@dial_display_goto_xy(device={device}, x={x}, y={y})")
        data = [int(device), ((x>>8)&0xFF), (x&0xFF), ((y>>8)&0xFF), (y&0xFF)]
        return self._sendCommand(self.commands.COMM_CMD_DISPLAY_GOTO_XY, self.data_type.COMM_DATA_SINGLE_VALUE, len(data), data)

    def display_send_image(self, device, img_filepath):
        logger.debug(f"@display_send_image(device={device}, img_filepath={img_filepath})")
        if not os.path.exists(img_filepath):
            logger.error(f"File '{img_filepath}' does not exist.")
            return False

        img_data = self.img_to_binary(img_filepath, True)
        return self.display_send_image_data(device, img_data)

    def display_send_image_data(self, device, imageData):
        logger.debug(f"@display_send_image_data(device={device}, imageData={imageData})")
        device = self._verify_device(device)

        # chunkSize = self._get_max_packet_size()
        chunkSize = 1000 # 1000 bytes at a time
        dataLen = len(imageData)
        chunks = math.ceil(len(imageData)/chunkSize)

        logger.debug(f"Split {dataLen} bytes into {chunks} chunks of {chunkSize} bytes.")

        start_time = time.time()
        for i in range(chunks):
            start = i*chunkSize
            end = i*chunkSize + chunkSize
            dataChunk = imageData[start:end]
            if not self._send_image_chunk(device, dataChunk):
                return False
            time.sleep(0.2)
        end_time = time.time()
        logger.debug(f"Send image data took {timedelta(seconds=end_time-start_time)}")
        return True

    def _send_image_chunk(self, device, imageBuffer):
        logger.debug(f"@_send_image_chunk(device={device})")
        if len(imageBuffer) <= 0:
            logger.error("Invalid image buffer size!")
            return False
        if isinstance(device, str):
            device = self._findDial(device)
            device = int(device)

        data = [ device ]
        data.extend(imageBuffer)
        return self._sendCommand(self.commands.COMM_CMD_DISPLAY_IMG_DATA, self.data_type.COMM_DATA_SINGLE_VALUE, len(data), data)

    def _format_bits(self, bits):
        buff = []
        for i in bits:
            if i > 127:
                buff.append(1)
            else:
                buff.append(0)
        return buff

    def binary_to_image_data(self, image):
        img = Image.open(Image.open(BytesIO(image)))
        img = img.convert("L")

        imgData = np.asarray(img)
        imgData = imgData.T.tolist()

        buff = []
        # Each byte is 8 vertical bits
        for bits in imgData:
            bits = self._format_bits(bits)
            byte = [int("".join(map(str, bits[i:i+8])), 2) for i in range(0, len(bits), 8)]
            buff.append(byte)

        buff = [item for sublist in buff for item in sublist]

        return buff

    def img_to_binary(self, img_filepath, flatten=True):
        buff = []

        if not os.path.exists(img_filepath):
            logger.error(f"File {img_filepath} does not exist!. Returning empty array.")
            return buff

        try:
            #Load image and convert to greyscale
            img = Image.open(img_filepath)
            img = img.convert("L")

            imgData = np.asarray(img)
            imgData = imgData.T.tolist()

            # Each byte is 8 vertical bits
            for bits in imgData:
                bits = self._format_bits(bits)
                byte = [int("".join(map(str, bits[i:i+8])), 2) for i in range(0, len(bits), 8)]
                buff.append(byte)

            if flatten:
                buff = [item for sublist in buff for item in sublist]
        except Exception as e:
            logger.error(e)

        return buff

    def update_display(self, device, imageData=None, imageFile=None):
        logger.debug(f"@update_display(device={device})")
        device = self._verify_device(device)

        self.dial_display_clear(device, True)
        self.dial_display_goto_xy(device, 0, 0)

        if imageData is not None:
            self.display_send_image_data(device, imageData)
        elif imageFile is not None:
            self.display_send_image(device, imageFile)
        else:
            raise ValueError("Image data and ImageFile can't both be none!")
        self.dial_display_show(device)
        return True


    def get_dial_rx_buffer_size(self, device):
        logger.debug(f"@get_dial_rx_buffer_size(device={device})")
        rxLen = self._sendCommand(self.commands.COMM_CMD_RX_BUFFER_SIZE, self.data_type.COMM_DATA_SINGLE_VALUE, 1, int(device))
        rxLen = int(rxLen[:8], 16)
        return rxLen

    def dial_display_show(self, device):
        logger.debug(f"@dial_display_show(device={device})")
        return self._sendCommand(self.commands.COMM_CMD_DISPLAY_SHOW_IMG, self.data_type.COMM_DATA_SINGLE_VALUE, 1, int(device))

    def dial_set_backlight(self, device, red, green, blue, white):
        logger.debug(f"@dial_set_backlight(device={device}, red={red}, green={green}, green={green}, blue={blue}, white={white})")
        device = self._verify_device(device)
        self.dials[device]['rgbw'][0] = red
        self.dials[device]['rgbw'][1] = green
        self.dials[device]['rgbw'][2] = blue
        self.dials[device]['rgbw'][3] = white
        data = [device, red, green, blue, white]
        return self._sendCommand(self.commands.COMM_CMD_SET_RGB_BACKLIGHT, self.data_type.COMM_DATA_MULTIPLE_VALUE, len(data), data)

    def dial_send_keep_comm_alive(self, device):
        pass
        # logger.debug(f"@dial_send_keep_comm_alive(device={device})")
        # device = self._verify_device(device)
        # return self._sendCommand(self.commands.DG_HUB_TO_DEV_KEEP_ALIVE, self.data_type.COMM_DATA_NONE)


    def provision_dials(self):
        logger.debug("@provision_dials")
        return self._sendCommand(self.commands.COMM_CMD_PROVISION_DEVICE, self.data_type.COMM_DATA_NONE)

    def reset_all_devices(self):
        logger.debug("@reset_all_devices")
        return self._sendCommand(self.commands.COMM_CMD_RESET_ALL_DEVICES, self.data_type.COMM_DATA_NONE)

    def debug_i2c_scan(self):
        logger.debug("@debug_i2c_scan")
        return self._sendCommand(self.commands.COMM_CMD_DEBUG_I2C_SCAN, self.data_type.COMM_DATA_NONE)

    def debug_print_all_dials(self):
        # Show found dials
        for entry in self.dials:
            dial = self.dials[entry]
            print(f"Dial #{dial['index']}")
            print(f"  - UID:{dial['uid']}")
            print(f"  - FriendlyName:{dial['friendlyName']}")
            print(f"  - Value:{dial['value']}")

    @classmethod
    def find_gauge_hub(cls):
        availablePorts = comports()
        logger.debug("Searching for COM port with VID:1027 and PID:24597")
        for port in availablePorts:
            logger.debug(f"{port.device}")
            logger.debug(f"\tProduct: {port.product}")
            logger.debug(f"\tDesc: {port.description}")
            logger.debug(f"\tSN: {port.serial_number}")
            logger.debug(f"\tVID:{port.vid} PID:{port.pid}")
            logger.debug(f"\tLocation: {port.location}")
            logger.debug(f"\tInterface: {port.interface}")
            if port.vid == 1027 and port.pid == 24597:
                logger.debug("Using '{}' as GaugeHub COM port".format(port.description))
                return port
        return None
