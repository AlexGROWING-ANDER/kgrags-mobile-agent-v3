import os
import time
import subprocess
import uiautomator2 as u2
from PIL import Image
from .controller import Controller

class AndroidController(Controller):
    _U2_NOT_CONNECTED = object()  # sentinel: u2 init attempted but failed

    def __init__(self, adb_path):
        self.adb_path = adb_path.rstrip() + " "
        self._u2_device = None  # None = not yet attempted

    @property
    def u2(self):
        """Lazy-init uiautomator2 device connection (attempted only once)."""
        if self._u2_device is None:
            try:
                result = subprocess.run(
                    f"{self.adb_path} devices", capture_output=True, text=True, shell=True
                )
                serials = [
                    line.split()[0]
                    for line in result.stdout.strip().splitlines()[1:]
                    if line.strip().endswith("device")
                ]
                serial = serials[0] if serials else None
                self._u2_device = u2.connect(serial) if serial else u2.connect()
            except Exception as e:
                print(f"Warning: uiautomator2 init failed: {e}, text input will fall back to ADB")
                self._u2_device = self._U2_NOT_CONNECTED
        return self._u2_device

    def get_screenshot(self, save_path):
        adb_executable = self.adb_path.strip()
        temporary_path = f"{save_path}.part"
        try:
            with open(temporary_path, "wb") as image_file:
                result = subprocess.run(
                    [adb_executable, "exec-out", "screencap", "-p"],
                    stdout=image_file,
                    stderr=subprocess.PIPE,
                )
            if result.returncode != 0 or os.path.getsize(temporary_path) == 0:
                return False

            # ADB can return success while the USB stream contains only a partial PNG.
            # Fully validate the temporary file before making it visible to the runner.
            with Image.open(temporary_path) as screenshot:
                screenshot.verify()
            with Image.open(temporary_path) as screenshot:
                screenshot.load()
                if screenshot.width <= 0 or screenshot.height <= 0:
                    return False

            os.replace(temporary_path, save_path)
            return True
        except (OSError, subprocess.SubprocessError):
            return False
        finally:
            if os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass

    def tap(self, x, y):
        command = self.adb_path + f" shell input tap {x} {y}"
        subprocess.run(command, capture_output=True, text=True, shell=True)

    def type(self, text):
        """Input text via uiautomator2 send_keys() — supports Chinese/Unicode natively."""
        if self.u2 is self._U2_NOT_CONNECTED:
            self._type_via_adb(text)
            return
        try:
            # Handle newlines: split by \n, send_keys each segment, press Enter between
            lines = text.replace("\\n", "\n").split("\n")
            for i, line in enumerate(lines):
                if line:
                    self.u2.send_keys(line)
                    time.sleep(0.3)
                if i < len(lines) - 1:
                    command = self.adb_path + " shell input keyevent 66"
                    subprocess.run(command, capture_output=True, text=True, shell=True)
                    time.sleep(0.3)
            time.sleep(0.5)
        except Exception as e:
            print(f"u2 send_keys failed ({e}), falling back to ADB input")
            self._type_via_adb(text)

    def _type_via_adb(self, text):
        """Fallback: character-by-character ADB input (ASCII only, Chinese requires ADB Keyboard IME)."""
        text = text.replace("\\n", "_").replace("\n", "_")
        for char in text:
            if char == ' ':
                command = self.adb_path + " shell input text %s"
                subprocess.run(command, capture_output=True, text=True, shell=True)
            elif char == '_':
                command = self.adb_path + " shell input keyevent 66"
                subprocess.run(command, capture_output=True, text=True, shell=True)
            elif 'a' <= char <= 'z' or 'A' <= char <= 'Z' or char.isdigit():
                command = self.adb_path + f" shell input text {char}"
                subprocess.run(command, capture_output=True, text=True, shell=True)
            elif char in '-.,!?@\'°/:;()':
                command = self.adb_path + f" shell input text \"{char}\""
                subprocess.run(command, capture_output=True, text=True, shell=True)
            else:
                command = self.adb_path + f" shell am broadcast -a ADB_INPUT_TEXT --es msg \"{char}\""
                subprocess.run(command, capture_output=True, text=True, shell=True)

    def slide(self, x1, y1, x2, y2):
        command = self.adb_path + f" shell input swipe {x1} {y1} {x2} {y2} 500"
        subprocess.run(command, capture_output=True, text=True, shell=True)

    def back(self):
        command = self.adb_path + " shell input keyevent 4"
        subprocess.run(command, capture_output=True, text=True, shell=True)

    def home(self):
        command = self.adb_path + " shell am start -a android.intent.action.MAIN -c android.intent.category.HOME"
        subprocess.run(command, capture_output=True, text=True, shell=True)

    def start_app(self, package):
        command = self.adb_path + f" shell monkey -p {package} -c android.intent.category.LAUNCHER 1"
        subprocess.run(command, capture_output=True, text=True, shell=True)

    def stop_app(self, package):
        command = self.adb_path + f" shell am force-stop {package}"
        subprocess.run(command, capture_output=True, text=True, shell=True)


