"""Lazy Chrome sessions with dedicated profiles and explicit worker ownership."""
from pathlib import Path
import os
import threading
from urllib3.exceptions import HTTPError

from .models import NeedsAttention


def default_profile_root():
    base = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / '.local' / 'share'))
    return base / 'ImageCollector' / 'browser-profiles'


class BrowserSession:
    def __init__(self, headless=False, profile_dir=None):
        self.headless = headless
        self.profile_dir = Path(profile_dir).resolve() if profile_dir is not None else None
        self._driver = None
        self._profile_lock = None

    @property
    def driver(self):
        if self._driver is None:
            self._acquire_profile()
            try:
                self._driver = self._create_driver()
            except Exception:
                self._release_profile()
                raise
        return self._driver

    def _acquire_profile(self):
        if self.profile_dir is None:
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        handle = (self.profile_dir / 'collector.lock').open('a+b')
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise NeedsAttention('수집기 Chrome 프로필을 다른 프로그램이 사용 중입니다. '
                                 '다른 이미지 수집기를 종료한 뒤 다시 시작하세요. '
                                 f'프로필: {self.profile_dir}') from exc
        self._profile_lock = handle

    def _release_profile(self):
        if self._profile_lock is not None:
            self._profile_lock.close()
            self._profile_lock = None

    def prepare(self):
        """Called between tasks; recover only when the existing Chrome has closed."""
        from selenium.common.exceptions import WebDriverException
        if self._driver is not None:
            try:
                handles = self._driver.window_handles
                if handles:
                    self._driver.switch_to.window(handles[0])
                    return
            except (WebDriverException, HTTPError, OSError):
                pass
            self.close()

    def _create_driver(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.common.exceptions import NoSuchDriverException, WebDriverException
        cache = Path(__file__).resolve().parents[1] / ".browser-cache"
        cache.mkdir(exist_ok=True)
        os.environ["SE_CACHE_PATH"] = str(cache / "selenium")
        options = Options()
        chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
        if chrome.exists():
            options.binary_location = str(chrome)
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--window-size=1400,1800")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-first-run")
        if self.profile_dir is not None:
            options.add_argument(f'--user-data-dir={self.profile_dir}')
        try:
            try:
                driver = webdriver.Chrome(options=options)
            except NoSuchDriverException:
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager
                from webdriver_manager.core.driver_cache import DriverCacheManager
                driver = webdriver.Chrome(service=Service(ChromeDriverManager(
                    cache_manager=DriverCacheManager(root_dir=str(cache))).install()), options=options)
        except WebDriverException as exc:
            raise NeedsAttention('수집기 Chrome을 시작하지 못했습니다. 수집기 전용 Chrome이 남아 있다면 '
                                 '닫고 다시 시도하세요. ' +
                                 (f'프로필: {self.profile_dir}' if self.profile_dir else '') +
                                 f' ({type(exc).__name__})') from exc
        try:
            driver.set_page_load_timeout(30)
            driver.set_script_timeout(10)
        except Exception:
            try:
                driver.quit()
            except (WebDriverException, HTTPError, OSError):
                pass
            raise
        return driver

    def close(self):
        from selenium.common.exceptions import WebDriverException
        driver, self._driver = self._driver, None
        try:
            if driver is not None:
                try:
                    driver.quit()
                except (WebDriverException, HTTPError, OSError):
                    pass  # A user may already have closed Chrome.
        finally:
            self._release_profile()


class BrowserPool:
    """An application worker owns both lazy visibility modes and closes them on exit."""
    def __init__(self, profile_root=None):
        self.profile_root = Path(profile_root) if profile_root is not None else default_profile_root()
        self.sessions = {}
        self._owner = None

    def _check_owner(self):
        owner = threading.get_ident()
        if self._owner is not None and self._owner != owner:
            raise RuntimeError('Chrome must be accessed on its owning worker thread.')
        self._owner = owner

    def get(self, headless=False):
        self._check_owner()
        if headless not in self.sessions:
            self.sessions[headless] = BrowserSession(headless=headless,
                profile_dir=self.profile_root / ('headless' if headless else 'visible'))
        browser = self.sessions[headless]
        browser.prepare()
        return browser

    def close(self):
        self._check_owner()
        try:
            for browser in self.sessions.values():
                browser.close()
        finally:
            self.sessions.clear()
