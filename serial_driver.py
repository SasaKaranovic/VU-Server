"""Line-framed serial transport for the VU1 hub: one locked write-then-read transaction per command."""
import time
from threading import Lock
import serial as _serial
import serial.tools.list_ports_common as _lpc
from serial.tools.list_ports import comports
from dials.base_logger import logger

DEFAULT_READ_TIMEOUT = 5


def find_port(predicate):
    """@returns the first ListPortInfo from comports() matching `predicate`, or None."""
    for port in comports():
        logger.debug(f"{port.device}")
        logger.debug(f"\tProduct: {port.product}")
        logger.debug(f"\tDesc: {port.description}")
        logger.debug(f"\tSN: {port.serial_number}")
        logger.debug(f"\tVID:{port.vid} PID:{port.pid}")
        logger.debug(f"\tLocation: {port.location}")
        logger.debug(f"\tInterface: {port.interface}")
        if predicate(port):
            logger.debug(f"Using '{port.device}' as GaugeHub COM port")
            return port
    return None


class SerialHardware:
    def __init__(self, port_info, timeout):
        """
        @param port_info a ListPortInfo, or a device path looked up among comports()
        @param timeout per-read and per-write port timeout in seconds
        """
        self.lock = Lock()

        if isinstance(port_info, str):
            logger.debug(f"Searching for COM port `{port_info}`")
            name = port_info
            port_info = find_port(lambda p: p.device == name)
        if not isinstance(port_info, _lpc.ListPortInfo):
            raise TypeError("The port_info for {} must be of type {}".format(self.__class__, _lpc.ListPortInfo))
        self.port_info = port_info

        self.port = _serial.Serial(
            port=self.port_info.device,
            baudrate=115200,
            timeout=timeout,
            write_timeout=timeout,
        )
        logger.debug(f"Serial driver initialized with timeout {timeout}s")

    def assert_open(self):
        if not self.port.is_open:
            raise _serial.SerialException("Serial port must be open. port: \"{}\" description \"{}\"".format(self.port_info.name, self.port_info.description))

    def read_until_response(self, timeout=DEFAULT_READ_TIMEOUT):
        """Read lines until one starts with '<' or the timeout passes; returns every line read."""
        rx_lines = []
        deadline = time.monotonic() + timeout
        while time.monotonic() <= deadline:
            line = self.handle_serial_read()
            if line:
                rx_lines.append(line)
                if line.startswith('<'):
                    break
        return rx_lines

    def handle_serial_read(self):
        """
        Read one line and decode it as utf-8.

        @return the stripped line, '' on a timeout or undecodable bytes, None if the port failed
        """
        try:
            return self.port.readline().decode("utf-8").strip()
        except UnicodeDecodeError as e:
            logger.error(e)
            return ""
        except _serial.SerialException as e:
            # A dropped device raises here; swallowing it keeps the serial worker thread alive.
            logger.error("Warning: serial read failed. port: \"{}\" description \"{}\": {}".format(self.port_info.name, self.port_info.description, e))
            return None

    def serial_transaction(self, payload, read_timeout=DEFAULT_READ_TIMEOUT):
        """
        Send one command line and read its response under the port lock.

        @param payload the command str, sent with a trailing CRLF
        @param read_timeout seconds to wait for a '<' reply
        @return every line read, ending with the '<' reply if one arrived
        """
        with self.lock:
            self.assert_open()

            # Leftover bytes from an aborted transaction must never be parsed as this command's reply.
            stale = self.port.in_waiting
            if stale:
                logger.debug(f"serial_transaction: discarding {stale} stale byte(s) before sending {payload!r}")
            self.port.reset_input_buffer()

            self.port.write((payload + '\r\n').encode())

            rx_lines = self.read_until_response(read_timeout)
            if not any(line.startswith('<') for line in rx_lines):
                logger.warning(f"serial_transaction: no valid response for {payload!r}; received {rx_lines!r}")
            return rx_lines
