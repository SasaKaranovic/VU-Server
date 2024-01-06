import re
import time
from threading import Lock
import serial as _serial
import serial.tools.list_ports as _lp
import serial.tools.list_ports_common as _lpc
from serial.tools.list_ports import comports
from dials.base_logger import logger


class SerialHardware(object):
    def __init__( self,
                 port_info,
                 flush_on_write=True,
                 serialPrefix = '',
                 serialSuffix = '\r\n',
                 timeout=0.2,
                 debug_uart=False):

        self.lock = Lock()

        self.flush_on_write = flush_on_write
        self.serialPrefix = serialPrefix
        self.serialSuffix = serialSuffix
        self.debug_uart = debug_uart

        # If port is string, find port by name
        if isinstance(port_info, str):
            self.port_info = self._find_port_by_name(port_info)
        else:
            self.port_info = port_info

        if not isinstance(self.port_info, _lpc.ListPortInfo):
            raise TypeError("The port_info for {} must be of type {}".format(self.__class__, _lpc.ListPortInfo))

        self.port = _serial.Serial(
            port=self.port_info.device,
            baudrate=115200,
            bytesize=_serial.EIGHTBITS,
            parity=_serial.PARITY_NONE,
            stopbits=_serial.STOPBITS_ONE,
            timeout=timeout, # seconds
            write_timeout=timeout, # seconds
        )


        if debug_uart:
            logger.info("Debug UART is set. UART RX/TX will be printed to debug log")

        logger.debug("Serial driver initialized with")
        logger.debug("-- flush_on_write: '{}'".format(self.flush_on_write))
        logger.debug("-- timeout: '{}'".format(timeout))

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def open(self):
        if self.is_open():
            if self.debug_uart:
                logger.debug("Port is already open")
            return
        self.port.open()
        self.port.reset_input_buffer()
        self.port.reset_output_buffer()
        if self.debug_uart:
            logger.debug("Port open and buffers flushed")

    def close(self):
        if not self.is_open():
            return
        self.port.reset_input_buffer()
        self.port.reset_output_buffer()
        self.port.close()

    def is_open(self):
        return self.port.is_open

    def assert_open(self):
        if not self.is_open():
            raise _serial.SerialException("Serial port must be open. port: \"{}\" description \"{}\"".format(self.port_info.name, self.description()))

    def get_port_info(self):
        return self.port_info

    def description(self):
        return self.port_info.description

    def _find_port_by_name(self, port_info):
        availablePorts = comports()
        logger.debug(f"Searching for COM port `{port_info}`")
        for port in availablePorts:
            logger.debug(f"{port.device}")
            logger.debug(f"\tProduct: {port.product}")
            logger.debug(f"\tDesc: {port.description}")
            logger.debug(f"\tSN: {port.serial_number}")
            logger.debug(f"\tVID:{port.vid} PID:{port.pid}")
            logger.debug(f"\tLocation: {port.location}")
            logger.debug(f"\tInterface: {port.interface}")
            if port.device == port_info:
                logger.debug("Using '{}' as GaugeHub COM port".format(port.device))
                return port
        return None

    def _read_until_re_match(self, status_re=None, timeout=2):
        """
        Read lines from serial until either a line containing status_re is found or timeout

        @param status_re regex, the status message you're waiting for
        @param timeout time to wait for respone
        @return tuple with True|False success|failure and the all the lines receiverd up
        to the line containing the status_re match. Never returns lines if no match is found
        """
        rx_lines = []

        compiled_re = re.compile(status_re, flags=re.IGNORECASE)

        timeout_timestmap = time.time() + timeout
        while time.time() <= timeout_timestmap:
            # Wait for new line
            line = self.handle_serial_read()
            if line:
                if self.debug_uart:
                    logger.debug(f"_read_until_re_match:{line}")
                rx_lines.append(line)
                if compiled_re.match(line):
                    return True, rx_lines
        return False, []

    def wait_for_re_string(self, regexstr=r'', timeout=30, return_all=False):
        status, lines = self._read_until_re_match(status_re=regexstr, timeout=timeout)
        if status:
            if return_all:
                return lines
            return True

        if return_all:
            return []
        return False

    def read_until_response(self, timeout=5):
        rx_lines = []

        timeout_timestmap = time.time() + timeout
        while time.time() <= timeout_timestmap:
            # Wait for new line
            line = self.handle_serial_read()
            if line:
                if self.debug_uart:
                    logger.debug(line)
                rx_lines.append(line)
                if line.startswith('<'):
                    break
            if time.time() > timeout_timestmap:
                logger.error(f"Timeout occured ({time.time()} > {timeout_timestmap})")
                break

        return rx_lines

    def handle_serial_send(self, command):
        """
        Basic implementations of serial write for the serial_transaction.
        Sends the passed string, depending on the object settings, adds
        a newline and/or flushes the in port before sending

        @param command the command str
        @return True if the command sent successfully
        """
        self.assert_open()
        command = self.serialPrefix + command + self.serialSuffix

        if self.flush_on_write and self.port.in_waiting > 0:
            logger.error("Warning: In bytes waiting. Discarded. Port: \"{}\" description \"{}\"".format(self.port_info.name, self.description()))

        if self.flush_on_write:
            self.port.reset_input_buffer()

        try:
            if self.debug_uart:
                logger.debug(f"Writting: '{command.encode()}'")
            self.port.write(command.encode())
            return True
        except _serial.SerialTimeoutException:
            logger.error("Warning: writing timed out. port: \"{}\" description \"{}\"".format(self.port_info.name, self.description()))
            return False

    def handle_serial_read(self):
        """
        Basic read implementation. Reads 1 line and decodes as utf-8

        @return the response str, None if the read fails or times out
        """
        try:
            response = self.port.readline()
            try:
                ret = response.decode("utf-8").strip()
            except Exception as e:
                logger.error(e)
                ret = ""
            return ret
        except _serial.SerialTimeoutException:
            logger.error("Warning: reading response timed out. port: \"{}\" description \"{}\"".format(self.port_info.name, self.description()))
            return None

        return None

    def serial_transaction(self, payload, ignore_response=False):
        """
        Wrapper to send a str payload to the serial port and get a response.
        Acquires the lock and asserts that the port is open and then calls the handle_serial_send
        If verify_response is set it reads until the response_re or default status_re is hit and return all lines up to that point or timeout
        Otherwise returns a single line from handle_serial_read
        handle_serial_read and handle_serial_send have default implementations that can be overridden

        @param payload the string serial payload passed to handle_serial_send
        @ignore_response don't read any response
        @return the result from the handle_serial_read sub payload
        """
        lines = []
        try:
            self.lock.acquire()
            self.assert_open()

            if not isinstance(payload, str) and not isinstance(payload, bytes) and not isinstance(payload, bytearray):
                raise TypeError("Serial_transaction expects str/bytes/bytearray")

            # Check if any messages were received
            while self.port.in_waiting:
                lines.append(self.handle_serial_read())

            if not self.handle_serial_send(payload):
                raise _serial.SerialException("Failed to send {}".format(payload))

            if not ignore_response:
                rx_lines = self.read_until_response()

            lines = rx_lines + lines

            return lines
        finally:
            self.lock.release()
