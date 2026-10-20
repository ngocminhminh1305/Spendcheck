"""HTTP clients for the five modules, with per-call timing.

Every call is timed and the timings of one request are returned to the browser in a
Server-Timing header (e.g. "extractor;dur=12.3, categoriser;dur=4.1"). The browser's developer
tools show them, and the system-level latency evaluation can read them per module.
"""

import time
from contextvars import ContextVar
from datetime import date, datetime
from typing import Any

import httpx

from .config import Settings

# Per-request state, set by the middleware in main.py.
current_timings: ContextVar[list[tuple[str, float]] | None] = ContextVar("current_timings", default=None)
current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)


class ServiceError(Exception):
    """A module could not be reached or answered with an error the gateway cannot handle."""

    def __init__(self, service: str, message: str, status: int | None = None):
        super().__init__(message)
        self.service, self.status = service, status


class Services:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.s = settings
        self.http = http or httpx.Client(timeout=httpx.Timeout(120.0, connect=5.0))

    def _call(self, service: str, method: str, url: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if request_id := current_request_id.get():
            headers["X-Request-ID"] = request_id   # one trace ID through every module
        started = time.perf_counter()
        try:
            return self.http.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as err:
            raise ServiceError(service, f"{service} is unreachable ({type(err).__name__})") from err
        finally:
            timings = current_timings.get()
            if timings is not None:
                timings.append((service, (time.perf_counter() - started) * 1000))

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        return detail if isinstance(detail, str) else response.text[:200]

    # ---- Module 1 -------------------------------------------------------------------------
    def extract(self, text: str, now: datetime) -> dict[str, Any]:
        r = self._call("extractor", "POST", f"{self.s.extractor_url}/extract",
                       json={"text": text, "reference_datetime": now.isoformat()})
        if r.status_code != 200:
            raise ServiceError("extractor", f"extractor error: {self._detail(r)}", r.status_code)
        return r.json()

    # ---- Module 2 -------------------------------------------------------------------------
    def classify(self, merchant: str) -> dict[str, Any]:
        """The category, or {"error": message} when Module 2 declines (ambiguous or invalid name).

        A 422 from Module 2 is an answer, not an outage: its README asks callers to let the user
        choose rather than treat it as a failure or silently assign "Other".
        """
        r = self._call("categoriser", "POST", f"{self.s.categoriser_url}/classify", json={"merchant": merchant})
        if r.status_code == 200:
            return r.json()
        if r.status_code == 422:
            return {"error": self._detail(r)}
        raise ServiceError("categoriser", f"categoriser error: {self._detail(r)}", r.status_code)

    # ---- Module 3 -------------------------------------------------------------------------
    def forecast(self, transactions: list[dict], as_of: date, budget: float | None) -> dict[str, Any]:
        r = self._call("forecaster", "POST", f"{self.s.forecaster_url}/forecast",
                       json={"transactions": transactions, "as_of": as_of.isoformat(), "budget": budget})
        if r.status_code != 200:
            raise ServiceError("forecaster", f"forecaster error: {self._detail(r)}", r.status_code)
        return r.json()

    # ---- Module 4 -------------------------------------------------------------------------
    def chat(self, user_id: str, body: dict) -> httpx.Response:
        """Returned as-is: the chat agent's 429 (rate limit) and 503 (no LLM) reach the browser."""
        return self._call("chat-agent", "POST", f"{self.s.chat_agent_url}/v1/chat",
                          json=body, headers={"X-User-Id": user_id})

    # ---- Module 5 -------------------------------------------------------------------------
    def documents(self) -> list[dict]:
        r = self._call("report-reader", "GET", f"{self.s.report_reader_url}/v1/documents")
        if r.status_code != 200:
            raise ServiceError("report-reader", f"report-reader error: {self._detail(r)}", r.status_code)
        return r.json()

    # ---- all ------------------------------------------------------------------------------
    def health(self) -> dict[str, bool]:
        """Which modules answer /health right now (for the site's status bar)."""
        urls = {"extractor": self.s.extractor_url, "categoriser": self.s.categoriser_url,
                "forecaster": self.s.forecaster_url, "chat-agent": self.s.chat_agent_url,
                "report-reader": self.s.report_reader_url}
        status = {}
        for name, url in urls.items():
            try:
                status[name] = self.http.get(f"{url}/health", timeout=3.0).status_code == 200
            except httpx.HTTPError:
                status[name] = False
        return status
