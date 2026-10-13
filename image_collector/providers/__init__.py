"""Search provider factory. Browser resources belong to the run."""
from .google import GoogleProvider
from .naver import NaverProvider
from .api import SerpApiProvider


def create_provider(engine, options, browser, stop_event=None, logger=None):
    if engine not in ("naver", "google"):
        raise ValueError("Unsupported search engine: " + engine)
    if options.backend == "api":
        if engine != "google":
            raise ValueError("The API backend supports Google only.")
        return SerpApiProvider(options, browser, stop_event, logger)
    cls = GoogleProvider if engine == "google" else NaverProvider
    return cls(options, browser, stop_event, logger)
