"""Anthropic cloud-route boundary with privacy and safe-failure handling."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable

import httpx
from dotenv import load_dotenv

from backend.privacy_shield import PrivacyShield


CLOUD_FAILURE_MESSAGE = "Cloud route selected, but the request could not be processed"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2026-10-21"
REQUEST_TIMEOUT_SECONDS = 30.0
CloudSender = Callable[[str, str], str]


@dataclass(frozen=True)
class CloudAdapterResult:
    answer: str | None
    message: str | None
    status: str
    processed: bool
    request_sent_to_cloud: bool
    cloud_latency_ms: float | None = None
    privacy_blocked: bool = False
    sensitive_data_types: tuple[str, ...] = ()
    reason_code: str | None = None


class _ProviderFailure(Exception):
    def __init__(self, reason_code: str, *, request_sent: bool) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.request_sent = request_sent


def _anthropic_sender(request_text: str, api_key: str, model: str) -> str:
    """Send one Messages API request and return only its text content."""

    try:
        response = httpx.post(
            ANTHROPIC_MESSAGES_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": request_text}],
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.ReadTimeout as error:
        raise _ProviderFailure("provider_timeout", request_sent=True) from error
    except httpx.TimeoutException as error:
        raise _ProviderFailure("provider_timeout", request_sent=False) from error
    except httpx.NetworkError as error:
        raise _ProviderFailure("network_failure", request_sent=False) from error
    except httpx.RequestError as error:
        raise _ProviderFailure("network_failure", request_sent=False) from error

    if response.status_code in (401, 403):
        raise _ProviderFailure("authentication_error", request_sent=True)
    if response.status_code in (400, 402):
        # Anthropic documents 400 for invalid requests and configured spend
        # limits, and 402 for billing/payment errors.
        raise _ProviderFailure("billing_or_request_error", request_sent=True)
    if response.status_code == 404:
        raise _ProviderFailure("model_not_found", request_sent=True)
    if response.status_code == 429:
        raise _ProviderFailure("rate_limited", request_sent=True)
    if not response.is_success:
        raise _ProviderFailure("provider_error", request_sent=True)

    try:
        payload = response.json()
        content = payload.get("content") if isinstance(payload, dict) else None
        answer = "".join(
            block.get("text", "")
            for block in content or []
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
    except (ValueError, TypeError, AttributeError):
        raise _ProviderFailure("provider_error", request_sent=True) from None

    if not answer.strip():
        raise _ProviderFailure("provider_error", request_sent=True)
    return answer.strip()


class CloudAdapter:
    """Call Anthropic only when configured and after the privacy check."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        sender: CloudSender | None = None,
        privacy_shield: PrivacyShield | None = None,
    ) -> None:
        load_dotenv(override=False)
        configured_key = api_key if api_key is not None else os.environ.get("CLOUD_API_KEY", "")
        self._api_key = configured_key.strip() or None
        configured_model = os.environ.get("CLOUD_MODEL", "")
        self._model = configured_model.strip() or None
        self._sender = sender
        self._privacy_shield = privacy_shield or PrivacyShield()

    @property
    def api_key_configured(self) -> bool:
        return self._api_key is not None

    @property
    def provider_configured(self) -> bool:
        return self._sender is not None or self._model is not None

    @property
    def is_configured(self) -> bool:
        return self.api_key_configured and self.provider_configured

    def configuration_status(self) -> dict[str, bool | str]:
        """Return safe booleans only; never return the configured key."""

        return {
            "status": "configured" if self.is_configured else "not_configured",
            "configured": self.is_configured,
            "api_key_configured": self.api_key_configured,
            "provider_configured": self.provider_configured,
        }

    def process(self, request_text: str) -> CloudAdapterResult:
        privacy_check = self._privacy_shield.inspect(request_text)
        if privacy_check.blocked:
            return CloudAdapterResult(
                answer=None,
                message=CLOUD_FAILURE_MESSAGE,
                status="blocked_by_privacy_shield",
                processed=False,
                request_sent_to_cloud=False,
                privacy_blocked=True,
                sensitive_data_types=privacy_check.detected_types,
                reason_code="privacy_blocked",
            )

        if not self._api_key:
            return self._failure(
                "missing_api_key", request_sent=False, status="cloud_not_configured"
            )
        if self._sender is None and not self._model:
            return self._failure("missing_model", request_sent=False)

        started_at = time.perf_counter()
        try:
            if self._sender is not None:
                provider_answer = self._sender(request_text, self._api_key)
            else:
                provider_answer = _anthropic_sender(request_text, self._api_key, self._model or "")
        except _ProviderFailure as error:
            return self._failure(
                error.reason_code,
                request_sent=error.request_sent,
                latency_ms=self._elapsed_ms(started_at),
                sensitive_data_types=privacy_check.detected_types,
            )
        except Exception:
            return self._failure(
                "provider_error",
                request_sent=True,
                latency_ms=self._elapsed_ms(started_at),
                sensitive_data_types=privacy_check.detected_types,
            )

        latency = self._elapsed_ms(started_at)
        if not isinstance(provider_answer, str) or not provider_answer.strip():
            return self._failure(
                "provider_error",
                request_sent=True,
                latency_ms=latency,
                sensitive_data_types=privacy_check.detected_types,
            )
        safe_answer = provider_answer.strip()
        if self._api_key and self._api_key in safe_answer:
            return self._failure(
                "provider_error",
                request_sent=True,
                latency_ms=latency,
                sensitive_data_types=privacy_check.detected_types,
            )
        return CloudAdapterResult(
            answer=safe_answer,
            message=None,
            status="completed",
            processed=True,
            request_sent_to_cloud=True,
            cloud_latency_ms=latency,
            sensitive_data_types=privacy_check.detected_types,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 2)

    @staticmethod
    def _failure(
        reason_code: str,
        *,
        request_sent: bool,
        latency_ms: float | None = None,
        sensitive_data_types: tuple[str, ...] = (),
        status: str | None = None,
    ) -> CloudAdapterResult:
        return CloudAdapterResult(
            answer=None,
            message=CLOUD_FAILURE_MESSAGE,
            status=status or reason_code,
            processed=False,
            request_sent_to_cloud=request_sent,
            cloud_latency_ms=latency_ms,
            sensitive_data_types=sensitive_data_types,
            reason_code=reason_code,
        )
