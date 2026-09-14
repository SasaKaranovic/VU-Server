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
        # A timeout with no valid '<' reply is reported once by the caller
        # (serial_transaction), so there's no separate timeout log here -- the
        # old inline check duplicated the loop guard and fired only sporadically.
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
            # Routine pre-write hygiene: serial_transaction already drains the RX
            # buffer, so leftover bytes here are expected, not an error condition.
            logger.debug("Discarding {} pre-write byte(s) on port \"{}\" ({})".format(self.port.in_waiting, self.port_info.name, self.description()))

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
        except _serial.SerialException as e:
            # readline() never raises SerialTimeoutException (that is write-only);
            # a read timeout just returns empty/partial bytes. The exception that
            # actually surfaces here is a SerialException when the device drops
            # mid-read. Swallow it so a disconnect can't kill the serial thread.
            logger.error("Warning: serial read failed. port: \"{}\" description \"{}\": {}".format(self.port_info.name, self.description(), e))
            return None

    def serial_transaction(self, payload, ignore_response=False, read_timeout=None):
        """
        Wrapper to send a str payload to the serial port and get a response.
        Acquires the lock and asserts that the port is open and then calls the handle_serial_send
        If verify_response is set it reads until the response_re or default status_re is hit and return all lines up to that point or timeout
        Otherwise returns a single line from handle_serial_read
        handle_serial_read and handle_serial_send have default implementations that can be overridden

        @param payload the string serial payload passed to handle_serial_send
        @ignore_response don't read any response
        @param read_timeout seconds to wait for the response; None uses read_until_response's default
        @return the result from the handle_serial_read sub payload
        """
        with self.lock:
            self.assert_open()

            if not isinstance(payload, str) and not isinstance(payload, bytes) and not isinstance(payload, bytearray):
                raise TypeError("Serial_transaction expects str/bytes/bytearray")

            # Drain and DISCARD any stale bytes left in the RX buffer from a
            # previous/aborted transaction. These must never be merged into this
            # command's response -- a leftover `<...>` line would otherwise be
            # parsed as though it were the reply to `payload`.
            stale_lines = []
            while self.port.in_waiting:
                line = self.handle_serial_read()
                if not line:
                    # A partial line (bytes with no terminator yet) or a failed
                    # read leaves in_waiting > 0 while readline() keeps returning
                    # empty -- the old loop spun here forever, holding the lock.
                    # Discard whatever raw bytes remain and stop draining.
                    self.port.reset_input_buffer()
                    break
                stale_lines.append(line)

            if stale_lines:
                logger.debug(f"serial_transaction: discarding {len(stale_lines)} stale buffered line(s) before sending {payload!r}: {stale_lines!r}")

            if not self.handle_serial_send(payload):
                raise _serial.SerialException("Failed to send {}".format(payload))

            if ignore_response:
                return []

            rx_lines = self.read_until_response() if read_timeout is None else self.read_until_response(timeout=read_timeout)
            if not any(line.startswith('<') for line in rx_lines):
                logger.warning(f"serial_transaction: no valid response for {payload!r}; received {rx_lines!r}")
            return rx_lines
