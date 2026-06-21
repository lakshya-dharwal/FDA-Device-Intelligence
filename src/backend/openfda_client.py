"""
Shared OpenFDA client with retries, timeouts, and normalized exceptions.
"""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.backend.exceptions import FDAUpstreamError, FDAUpstreamTimeoutError

logger = logging.getLogger(__name__)

OPENFDA_BASE = "https://api.fda.gov"
RETRYABLE_STATUS_CODES = [429, 500, 502, 503, 504]
DEFAULT_TIMEOUT = (3.05, 10)

_session = requests.Session()
_session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.5,
            status_forcelist=RETRYABLE_STATUS_CODES,
            allowed_methods=frozenset(["GET"]),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
    ),
)


def _extract_upstream_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or "No upstream error details returned."

    error = payload.get("error")
    if isinstance(error, dict):
        return error.get("message", "No upstream error details returned.")
    return "No upstream error details returned."


def get_json(path: str, params: dict) -> dict:
    """Perform a GET request against OpenFDA and return parsed JSON."""
    url = f"{OPENFDA_BASE}{path}"
    try:
        response = _session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    except requests.Timeout as exc:
        raise FDAUpstreamTimeoutError(
            details={"url": url, "params": params},
        ) from exc
    except requests.RequestException as exc:
        raise FDAUpstreamError(
            "Could not reach the FDA data source.",
            details={"url": url, "params": params, "reason": str(exc)},
        ) from exc

    if response.status_code == 404:
        return {"results": []}

    if response.status_code >= 400:
        message = _extract_upstream_message(response)
        logger.warning(
            "OpenFDA request failed",
            extra={
                "url": url,
                "params": params,
                "status_code": response.status_code,
                "upstream_message": message,
            },
        )
        raise FDAUpstreamError(
            "The FDA data source returned an error.",
            details={
                "url": url,
                "params": params,
                "status_code": response.status_code,
                "upstream_message": message,
            },
            retryable=response.status_code in RETRYABLE_STATUS_CODES,
        )

    try:
        return response.json()
    except ValueError as exc:
        raise FDAUpstreamError(
            "The FDA data source returned an invalid response.",
            details={"url": url, "params": params},
        ) from exc
