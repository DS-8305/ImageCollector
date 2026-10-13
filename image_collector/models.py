"""Shared contracts for independent search providers and the download pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib


class CollectionError(RuntimeError):
    pass


class NeedsAttention(CollectionError):
    pass


class Cancelled(CollectionError):
    pass


class RejectedImage(CollectionError):
    pass


class DuplicateImage(RejectedImage):
    pass


class DownloadBudgetExceeded(RejectedImage):
    """A download operation cannot continue within the keyword time budget."""
    pass


PROFILES = {
    "legacy-thumbnail": (150, 150, 0),
    "blog": (150, 150, 1200),
    "video-landscape": (1920, 1080, 0),
    "video-portrait": (1080, 1920, 0),
    "custom": (150, 150, 0),
}


@dataclass(frozen=True, slots=True)
class Candidate:
    thumbnail_url: str
    source_url: str = ""
    title: str = ""
    source: str = ""
    original_url: str = ""
    engine: str = ""
    rank: int = 0
    license_url: str = ""

    @property
    def candidate_id(self) -> str:
        return hashlib.sha256((self.engine + "|" + (self.original_url or self.thumbnail_url)).encode()).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ResolvedOptions:
    engine: str
    limit: int
    download_mode: str
    profile: str
    min_width: int
    min_height: int
    min_long_edge: int
    headless: bool
    max_candidates: int
    max_scrolls: int
    keyword_timeout: float
    backend: str
    period: str
    usage_rights: str

    def accepts_size(self, width: int, height: int) -> bool:
        return width >= self.min_width and height >= self.min_height and max(width, height) >= self.min_long_edge


@dataclass(frozen=True, slots=True)
class CollectionOptions:
    engine: str = "naver"
    limit: int = 50
    download_mode: str | None = None
    profile: str | None = None
    min_width: int | None = None
    min_height: int | None = None
    min_long_edge: int | None = None
    headless: bool | None = None
    max_candidates: int | None = None
    max_scrolls: int = 30
    keyword_timeout: float = 300
    backend: str = "browser"
    period: str = ""
    usage_rights: str = ""

    @property
    def engines(self) -> tuple[str, ...]:
        if self.engine not in ("naver", "google", "both"):
            raise ValueError("검색엔진은 naver, google, both 중 하나여야 합니다.")
        return ("naver", "google") if self.engine == "both" else (self.engine,)

    def resolve(self, engine: str | None = None) -> ResolvedOptions:
        engines = self.engines
        engine = engine or engines[0]
        if engine not in engines:
            raise ValueError("선택한 검색엔진에 맞지 않는 옵션입니다.")
        if self.limit < 1 or self.max_scrolls < 1 or self.keyword_timeout <= 0:
            raise ValueError("저장 수, 스크롤 횟수와 제한 시간은 양수여야 합니다.")
        mode = self.download_mode or ("thumbnail" if engine == "naver" else "original-only")
        if mode not in ("thumbnail", "original-preferred", "original-only"):
            raise ValueError("지원하지 않는 다운로드 방식입니다.")
        if engine == "naver" and mode != "thumbnail":
            raise ValueError("네이버는 현재 썸네일 저장만 지원합니다.")
        profile = self.profile or ("legacy-thumbnail" if mode == "thumbnail" else "blog")
        if profile not in PROFILES:
            raise ValueError("지원하지 않는 크기 프리셋입니다.")
        width, height, edge = PROFILES[profile]
        override = any(value is not None for value in (self.min_width, self.min_height, self.min_long_edge))
        width = width if self.min_width is None else self.min_width
        height = height if self.min_height is None else self.min_height
        edge = edge if self.min_long_edge is None else self.min_long_edge
        if width < 1 or height < 1 or edge < 0:
            raise ValueError("가로·세로는 1 이상, 긴 변은 0 이상이어야 합니다.")
        max_candidates = self.max_candidates if self.max_candidates is not None else max(100, self.limit * 5)
        if max_candidates < 1:
            raise ValueError("후보 제한은 1 이상이어야 합니다.")
        if self.backend not in ("browser", "api"):
            raise ValueError("수집 방식은 browser 또는 api여야 합니다.")
        if self.backend == "api" and engine != "google":
            raise ValueError("외부 검색 API는 구글 선택에서만 사용할 수 있습니다.")
        if self.period not in ("", "day", "week", "month", "year"):
            raise ValueError("검색 기간이 올바르지 않습니다.")
        if self.usage_rights not in ("", "creative-commons", "commercial"):
            raise ValueError("사용 권한 필터가 올바르지 않습니다.")
        if engine == "naver" and (self.period or self.usage_rights):
            raise ValueError("현재 고급 기간·사용 권한 필터는 구글에서만 지원합니다.")
        return ResolvedOptions(engine, self.limit, mode, "custom" if override else profile,
                               width, height, edge,
                               self.headless if self.headless is not None else engine == "naver",
                               max_candidates, self.max_scrolls, self.keyword_timeout,
                               self.backend, self.period, self.usage_rights)


@dataclass(frozen=True, slots=True)
class DownloadedImage:
    png_bytes: bytes
    width: int
    height: int
    content_hash: str
    downloaded_url: str
    download_kind: str
    fallback_reason: str = ""


@dataclass(frozen=True, slots=True)
class JobResult:
    keyword: str
    engine: str
    saved_count: int
    status: str
    error: str = ""
    requested_count: int = 50
    original_count: int = 0
    thumbnail_count: int = 0
    folder: str = ""


@dataclass(frozen=True, slots=True)
class RunResult:
    run_dir: Path
    jobs: list[JobResult]
    status: str

    @property
    def saved_count(self) -> int:
        return sum(job.saved_count for job in self.jobs)
