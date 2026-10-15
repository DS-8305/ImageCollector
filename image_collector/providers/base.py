"""Shared bounds and page-state handling for search adapters."""
import time
from urllib.parse import urlparse
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from image_collector.budget import ActiveBudget
from image_collector.models import ResolvedOptions, Candidate, Cancelled, CollectionError, NeedsAttention


def http_url(value):
    value = str(value or "").strip()
    parsed = urlparse(value)
    return value if parsed.scheme in ("http", "https") and parsed.netloc else ""


def thumbnail_url(value):
    value = str(value or "").strip()
    return value if value.startswith(("data:image/jpeg;", "data:image/png;", "data:image/webp;")) else http_url(value)


class BrowserProvider:
    def __init__(self, options: ResolvedOptions, browser, stop_event=None, logger=None):
        self.options = options
        self.browser = browser
        self.stop_event = stop_event
        self.logger = logger
        self.budget = ActiveBudget(0)
        self.verification_timeout = 600
        self.verification_seconds = 0
        self.verification_callback = None
        self.diagnostic_dir = None

    @property
    def deadline(self):
        return self.budget.deadline

    @deadline.setter
    def deadline(self, value):
        self.budget.deadline = value

    def check_cancelled(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise Cancelled("Image search cancelled.")

    def remaining(self):
        self.check_cancelled()
        return max(0, self.deadline - time.monotonic())

    def page_state(self):
        driver = self.browser.driver
        state = driver.execute_script("""
            return {text:(document.body?.innerText||'').toLowerCase(),
              blocked:!!document.querySelector('#captcha-form, .g-recaptcha, iframe[src*="recaptcha"]'),
              consent:!!document.querySelector('form[action*="consent.google"],form[action*="consent.youtube"]')};
        """) or {}
        text = state.get("text", "")
        url = driver.current_url.lower()
        if state.get("blocked") or "/sorry/" in url or any(x in text for x in (
                "unusual traffic", "automated queries", "비정상적인 트래픽", "접근이 제한", "자동입력 방지")):
            raise NeedsAttention("Search engine verification or traffic block requires user attention.")
        if state.get("consent") or "consent.google." in url or "before you continue to google" in text:
            raise NeedsAttention("Google consent screen requires user attention.")
        if any(x in text for x in ("did not match any documents", "no image results found", "no results found",
                                    "검색결과가 없습니다", "검색 결과가 없습니다", "이미지 검색결과가 없습니다")) and not self.read_cards():
            return "empty"
        return "unknown"

    def wait(self, condition, timeout=10):
        end = time.monotonic() + min(timeout, self.remaining())
        while self.remaining() > 0:
            self.check_cancelled()
            paused = self.budget.paused_seconds
            self.await_page_state()
            end += self.budget.paused_seconds - paused
            if self.remaining() <= 0 or time.monotonic() >= end:
                return None
            try:
                result = condition(self.browser.driver)
                if result:
                    return result
            except NoSuchElementException:
                pass
            self._sleep(min(.1, self.remaining(), max(0, end-time.monotonic())))
        return None

    def _sleep(self, seconds):
        if self.stop_event is not None:
            self.stop_event.wait(seconds)
        else:
            time.sleep(seconds)

    def await_page_state(self):
        """Keep a visible verification page available for manual user action."""
        try:
            return self.page_state()
        except NeedsAttention as attention:
            if self.options.headless:
                raise
            if self.logger:
                self.logger("사용자 확인 필요: 같은 Chrome 창에서 캡차 또는 동의를 처리하세요. "
                            "확인 대기 시간은 수집 제한 시간에서 제외합니다.")
            if self.verification_callback:
                self.verification_callback(waiting=True)
            start = time.monotonic()
            manual_end = start + max(0, self.verification_timeout-self.verification_seconds)
            resolved = False
            with self.budget.pause():
                try:
                    while time.monotonic() < manual_end:
                        self.check_cancelled()
                        try:
                            state = self.page_state()
                            resolved = True
                            if self.logger:
                                self.logger("브라우저 확인 완료: 같은 세션에서 수집을 계속합니다.")
                            return state
                        except NeedsAttention:
                            self._sleep(min(.2, max(0, manual_end-time.monotonic())))
                    self.check_cancelled()
                    raise NeedsAttention("브라우저 확인 대기 시간이 끝났습니다. 저장 결과를 보존했습니다. "
                                         "확인 후 이어받기를 누르세요.") from attention
                finally:
                    self.verification_seconds += time.monotonic()-start
                    if self.verification_callback:
                        self.verification_callback(waiting=False, resolved=resolved)

    def read_cards(self):
        return self.browser.driver.execute_script(self.cards_script) or []

    def candidate(self, card, rank):
        return Candidate(thumbnail_url=thumbnail_url(card.get("thumbnail")),
                         source_url=http_url(card.get("source_url")),
                         title=str(card.get("title") or ""), source=str(card.get("source") or ""),
                         engine=self.engine, rank=rank)

    def search(self, keyword):
        self.check_cancelled()
        self.deadline = time.monotonic() + self.options.keyword_timeout
        self.verification_seconds = 0
        driver = self.browser.driver
        driver.set_page_load_timeout(min(30, self.options.keyword_timeout))
        try:
            driver.get(self.search_url(keyword))
            ready = self.wait(lambda _d: self.read_cards() or (self.page_state() == "empty"))
            if self.await_page_state() == "empty":
                return
            if not ready:
                raise CollectionError(f"{self.engine} result structure was not recognized before the search deadline.")
            seen = set()
            stale = 0
            for _ in range(self.options.max_scrolls):
                self.check_cancelled()
                self.await_page_state()
                cards = self.read_cards()
                before = len(seen)
                for card in cards:
                    self.check_cancelled()
                    if self.remaining() <= 0:
                        return
                    thumb = thumbnail_url(card.get("thumbnail"))
                    identity = card.get("id") or thumb
                    if not thumb or identity in seen:
                        continue
                    seen.add(identity)
                    yield self.candidate(card, len(seen))
                    if len(seen) >= self.options.max_candidates:
                        return
                stale = stale + 1 if len(seen) == before else 0
                if stale >= 3 or self.remaining() <= 0:
                    return
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                count = len(cards)
                self.wait(lambda _d: len(self.read_cards()) > count, timeout=1)
            if not seen:
                raise CollectionError(f"{self.engine} result cards contain no readable images; selectors may need updating.")
        except (Cancelled, NeedsAttention, CollectionError):
            raise
        except WebDriverException as exc:
            self.check_cancelled()
            raise CollectionError(f"{self.engine} browser search failed ({type(exc).__name__}).") from exc

    def close(self):
        # The runner owns its shared BrowserSession.
        pass
