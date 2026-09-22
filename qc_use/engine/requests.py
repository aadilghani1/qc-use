"""Bound model transport retries and retain safe diagnostics for each attempt."""

import random
import threading
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from .errors import ProviderUnavailable

RETRY_SECONDS = 45.0
TRANSIENT = {429, 502, 503, 504, 529}


def retry_delay(response, attempt):
    """Respect Retry-After; otherwise use capped exponential backoff with jitter."""
    value = response.headers.get("Retry-After") if response is not None else None
    if value:
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                seconds = -1
        if 0 <= seconds < float("inf"):
            return seconds
    cap = min(8, 0.5 * 2 ** min(attempt, 5))
    return random.uniform(cap / 2, cap)


def diagnostics(response, redact, credential):
    """Keep bounded error fields and request IDs, never headers or entire response bodies."""

    def safe(value):
        value = str(value).replace(credential, "[provider credential]") if credential else str(value)
        return (redact.text(value) if redact else value)[:300]

    result = {}
    for key in ("x-vercel-id", "x-request-id"):
        if value := response.headers.get(key):
            result[key] = safe(value)
    try:
        body = response.json()
    except ValueError:
        return result

    def fields(value, depth=0):
        if not isinstance(value, dict) or depth > 4:
            return
        for key, item in value.items():
            if key in {"message", "type", "code", "provider", "provider_name", "providerName"} and isinstance(
                item, str
            ):
                result.setdefault(key, safe(item))
            elif key in {"error", "metadata", "cause", "providerMetadata"}:
                fields(item, depth + 1)

    fields(body)
    return result


def bounded_post(client, url, key, body, remaining):
    """Bound caller wait even when a transport stalls; a late response cannot trigger input."""
    finished = threading.Event()
    result = {}

    def send():
        try:
            result["response"] = client.post(
                url, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=min(25, remaining)
            )
        except Exception as error:
            result["error"] = error
        finally:
            finished.set()

    # The worker only sends one model request. No retry, metering, or browser action runs on it.
    threading.Thread(target=send, daemon=True).start()
    if not finished.wait(remaining):
        raise ProviderUnavailable(
            "Provider unavailable: model request deadline expired; no further model requests sent."
        )
    if "error" in result:
        raise result["error"]
    return result["response"]


def unpriced(meter, record):
    """Retain unknown charges when a sent request has no usable response."""
    record["pricing"] = {"source": "unknown", "usd": None, "status": "unavailable"}
    if meter:
        meter.unpriced += 1
        meter.pricing.append(record["pricing"])


def send(client, url, key, body, meter, redact, purpose):
    """Retry transient failures within one deadline and the run's request cap."""
    deadline = time.monotonic() + RETRY_SECONDS
    attempt = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderUnavailable(
                "Provider unavailable: model retry deadline expired; inspect the page before rerunning."
            )
        if meter:
            meter.check()
        attempt += 1
        record = {
            "attempt": attempt,
            "provider": urlparse(url).hostname,
            "purpose": purpose,
            "status": None,
            "retry_seconds": 0.0,
        }
        if meter:
            meter.requests.append(record)
        started = time.monotonic()
        response = None
        try:
            response = bounded_post(client, url, key, body, remaining)
            record["status"] = response.status_code
            if time.monotonic() >= deadline:
                raise ProviderUnavailable("Provider unavailable: response arrived after the model request deadline.")
        except ProviderUnavailable:
            record["status"] = "deadline_exceeded"
            unpriced(meter, record)
            raise
        except httpx.TransportError as error:
            record["status"] = "transport_error"
            if not isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
                unpriced(meter, record)
                raise ProviderUnavailable(
                    "Provider unavailable: response lost after request started; cost unknown. No further requests sent."
                ) from None
        finally:
            record["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        if response is not None:
            if response.is_error:
                record["error"] = diagnostics(response, redact, key)
            if not response.is_error:
                return response, record
            if response.status_code not in TRANSIENT:
                raise RuntimeError(
                    f"Model provider returned HTTP {response.status_code}; inspect trace.json for details."
                )
        remaining = deadline - time.monotonic()
        delay = retry_delay(response, attempt - 1)
        if remaining <= 0 or delay >= remaining:
            raise ProviderUnavailable(
                f"Provider unavailable after {attempt} attempts ({record['status']}); retry deadline exhausted."
            )
        record["retry_seconds"] = delay
        time.sleep(delay)
