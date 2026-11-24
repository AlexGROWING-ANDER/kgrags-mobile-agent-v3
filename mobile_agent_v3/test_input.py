"""
Test script for AndroidController.type() input functionality.
Tests English, Chinese, numbers, punctuation, spaces, and mixed input
using the Baidu Search app.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mobile_v3'))
from utils.android_controller import AndroidController

ADB_PATH = "/Users/xudonglai/Library/Android/sdk/platform-tools/adb"
SCREENSHOT_DIR = "/tmp/mobile_test"
BAIDU_PACKAGE = "com.baidu.searchbox"

# Search bar coordinates on 1080x2400 device (Baidu homepage)
SEARCH_BAR_X = 540
SEARCH_BAR_Y = 140

# Clear button coordinates (X button on the right side of search bar)
CLEAR_BTN_X = 1020
CLEAR_BTN_Y = 140


def take_screenshot(controller, name):
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    for _ in range(3):
        if controller.get_screenshot(path):
            print(f"  Screenshot saved: {path}")
            return path
        time.sleep(1)
    print(f"  Failed to take screenshot: {name}")
    return None


def clear_search_field(controller):
    """Select all text and delete it"""
    # Long press to select, then delete
    controller.tap(CLEAR_BTN_X, CLEAR_BTN_Y)
    time.sleep(0.5)


def launch_baidu(controller):
    """Launch Baidu and wait for it to load"""
    print("Launching Baidu Search...")
    controller.stop_app(BAIDU_PACKAGE)
    time.sleep(2)
    controller.home()
    time.sleep(1)
    controller.start_app(BAIDU_PACKAGE)
    time.sleep(5)
    take_screenshot(controller, "00_baidu_home")


def tap_search_bar(controller):
    """Tap on the search bar to focus it"""
    print("Tapping search bar...")
    controller.tap(SEARCH_BAR_X, SEARCH_BAR_Y)
    time.sleep(2)
    take_screenshot(controller, "01_search_focused")


def run_test(controller, test_name, text, step_num):
    """Run a single typing test"""
    print(f"\n{'='*60}")
    print(f"Test {step_num}: {test_name}")
    print(f"  Input text: {repr(text)}")
    print(f"{'='*60}")

    # Clear previous text
    clear_search_field(controller)
    time.sleep(1)

    # Type the text
    print(f"  Typing...")
    controller.type(text)
    time.sleep(2)

    # Take screenshot to verify
    take_screenshot(controller, f"{step_num:02d}_{test_name}")
    print(f"  Done!")


def main():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    controller = AndroidController(ADB_PATH)

    # Launch Baidu
    launch_baidu(controller)

    # Tap on search bar
    tap_search_bar(controller)

    # Define test cases
    tests = [
        ("english",       "Hello World"),
        ("numbers",       "1234567890"),
        ("punctuation",   "test-.,!?@'/:;()"),
        ("chinese",       "你好世界"),
        ("mixed",         "Hello你好123!"),
        ("url",           "www.baidu.com"),
        ("email",         "test@example.com"),
        ("long_text",     "Mobile Agent v3 test 测试输入功能"),
    ]

    for i, (name, text) in enumerate(tests, start=2):
        run_test(controller, name, text, i)

    print(f"\n{'='*60}")
    print("All tests completed! Screenshots saved to:", SCREENSHOT_DIR)
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
