# pylint: disable=import-outside-toplevel
import sys

# TODO: Add support for Linux and Mac OS

if sys.platform.lower() == "win32":
    import ctypes

    def show_error_msg(title, message):
        ctypes.windll.user32.MessageBoxW(0, message, f"VU Server - {title}", 16)

    def show_warning_msg(title, message):
        ctypes.windll.user32.MessageBoxW(0, message, f"VU Server - {title}", 48)

    def show_info_msg(title, message):
        ctypes.windll.user32.MessageBoxW(0, message, f"VU Server - {title}", 64)

else:
    def show_error_msg(title, message):
        print(f"VU Server - {title}")
        print(message)

    def show_warning_msg(title, message):
        print(f"VU Server - {title}")
        print(message)

    def show_info_msg(title, message):
        print(f"VU Server - {title}")
        print(message)
