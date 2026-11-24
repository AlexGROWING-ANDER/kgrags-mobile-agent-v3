import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image


MOBILE_V3_ROOT = Path(__file__).resolve().parents[1]
if str(MOBILE_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(MOBILE_V3_ROOT))

from run_mobileagentv3 import capture_screenshot_or_raise
from utils.android_controller import AndroidController


def make_png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 6), color="navy").save(output, format="PNG")
    return output.getvalue()


class AndroidScreenshotTests(unittest.TestCase):
    def test_valid_png_is_atomically_published(self):
        png_data = make_png_bytes()

        def fake_run(_command, **kwargs):
            kwargs["stdout"].write(png_data)
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "screen.png"
            controller = AndroidController("adb")
            with patch("utils.android_controller.subprocess.run", side_effect=fake_run):
                self.assertTrue(controller.get_screenshot(str(target)))

            self.assertTrue(target.exists())
            self.assertFalse(Path(f"{target}.part").exists())
            with Image.open(target) as screenshot:
                self.assertEqual(screenshot.size, (8, 6))

    def test_truncated_png_is_rejected_and_cleaned_up(self):
        truncated = make_png_bytes()[:20]

        def fake_run(_command, **kwargs):
            kwargs["stdout"].write(truncated)
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "screen.png"
            controller = AndroidController("adb")
            with patch("utils.android_controller.subprocess.run", side_effect=fake_run):
                self.assertFalse(controller.get_screenshot(str(target)))

            self.assertFalse(target.exists())
            self.assertFalse(Path(f"{target}.part").exists())

    def test_capture_retries_then_succeeds(self):
        class RetryController:
            def __init__(self):
                self.calls = 0

            def get_screenshot(self, _save_path):
                self.calls += 1
                return self.calls == 3

        controller = RetryController()
        capture_screenshot_or_raise(controller, "unused.png", attempts=3, retry_delay=0)
        self.assertEqual(controller.calls, 3)

    def test_capture_raises_after_all_attempts_fail(self):
        class FailedController:
            def get_screenshot(self, _save_path):
                return False

        with self.assertRaisesRegex(RuntimeError, "after 2 attempts"):
            capture_screenshot_or_raise(
                FailedController(), "broken.png", attempts=2, retry_delay=0
            )


if __name__ == "__main__":
    unittest.main()
