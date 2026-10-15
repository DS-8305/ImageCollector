"""Dedicated profiles and browser ownership using real local Chrome."""
import tempfile
from pathlib import Path
import threading
import unittest
from unittest.mock import MagicMock, PropertyMock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from image_collector.browser import BrowserSession
from image_collector.models import NeedsAttention


class BrowserTests(unittest.TestCase):
    def test_lost_driver_transport_is_recoverable(self):
        from urllib3.exceptions import MaxRetryError
        failed = MagicMock()
        type(failed).window_handles = PropertyMock(side_effect=MaxRetryError(None, '/session'))
        failed.quit.side_effect = MaxRetryError(None, '/quit')
        replacement = MagicMock()
        with tempfile.TemporaryDirectory() as root:
            browser = BrowserSession(headless=True, profile_dir=Path(root))
            with patch.object(browser, '_create_driver', side_effect=[failed, replacement]):
                try:
                    self.assertIs(browser.driver, failed)
                    browser.prepare()
                    self.assertIs(browser.driver, replacement)
                finally:
                    browser.close()

    def test_setup_failure_quits_driver_and_releases_profile(self):
        driver = MagicMock()
        driver.set_script_timeout.side_effect = RuntimeError('setup failed')
        with tempfile.TemporaryDirectory() as root:
            first = BrowserSession(headless=True, profile_dir=Path(root))
            with patch('selenium.webdriver.Chrome', return_value=driver):
                with self.assertRaisesRegex(RuntimeError, 'setup failed'):
                    _ = first.driver
            driver.quit.assert_called_once()
            second = BrowserSession(headless=True, profile_dir=Path(root))
            with patch.object(second, '_create_driver', return_value=MagicMock()):
                try:
                    _ = second.driver
                finally:
                    second.close()

    def test_profile_cookie_survives_browser_restart_and_window_close_recovers(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'<title>Local profile test</title>')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as root:
                profile = Path(root) / 'profile'
                browser = BrowserSession(headless=True, profile_dir=profile)
                url = f'http://127.0.0.1:{server.server_port}/'
                try:
                    driver = browser.driver
                    driver.get(url)
                    driver.add_cookie({'name': 'collector_test', 'value': 'retained',
                                       'expiry': 2147483647})
                    browser.close()
                    browser = BrowserSession(headless=True, profile_dir=profile)
                    driver = browser.driver
                    driver.get(url)
                    self.assertEqual(driver.get_cookie('collector_test')['value'], 'retained')
                    first_id = driver.session_id
                    driver.close()
                    browser.prepare()
                    self.assertNotEqual(browser.driver.session_id, first_id)
                    browser.driver.get(url)
                    self.assertEqual(browser.driver.get_cookie('collector_test')['value'], 'retained')
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_same_profile_cannot_be_opened_twice_and_lock_is_released(self):
        with tempfile.TemporaryDirectory() as root:
            first = BrowserSession(headless=True, profile_dir=Path(root))
            second = BrowserSession(headless=True, profile_dir=Path(root))
            try:
                first.driver.get('data:text/html,<title>first</title>')
                with self.assertRaisesRegex(NeedsAttention, '프로필'):
                    _ = second.driver
                first.close()
                second.driver.get('data:text/html,<title>second</title>')
                self.assertEqual(second.driver.title, 'second')
            finally:
                first.close()
                second.close()
