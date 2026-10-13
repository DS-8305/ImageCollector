"""Lazily create one Chrome for a collection run."""
from pathlib import Path
import os


class BrowserSession:
    def __init__(self, headless=False):
        self.headless = headless
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            self._driver = self._create_driver()
        return self._driver

    def _create_driver(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.common.exceptions import WebDriverException
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
        try:
            driver = webdriver.Chrome(options=options)
        except WebDriverException:
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            from webdriver_manager.core.driver_cache import DriverCacheManager
            driver = webdriver.Chrome(service=Service(ChromeDriverManager(
                cache_manager=DriverCacheManager(root_dir=str(cache))).install()), options=options)
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(10)
        return driver

    def close(self):
        driver, self._driver = self._driver, None
        if driver is not None:
            driver.quit()
