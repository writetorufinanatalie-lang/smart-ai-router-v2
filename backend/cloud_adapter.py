"""Cloud-route boundary that refuses to invent provider responses."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable

from dotenv import load_dotenv

from backend.privacy_shield import PrivacyShield


CLOUD_FAILURE_MESSAGE = "Cloud route selected, but the request could not be processed"
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


class CloudAdapter:
    """Call only an explicitly supplied provider sender with a configured key.

    No provider or sender is configured in this project yet. Therefore the
    default adapter always returns an honest unavailable result, even if a key
    happens to exist in the environment.
    """

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
        self._sender = sender
        self._privacy_shield = privacy_shield or PrivacyShield()

    @property
    def api_key_configured(self) -> bool:
        return self._api_key is not None

    @property
    def provider_configured(self) -> bool:
        return self._sender is not None

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
            )

        if not self._api_key or self._sender is None:
            return CloudAdapterResult(
                answer=None,
                message=CLOUD_FAILURE_MESSAGE,
                status="cloud_not_configured",
                processed=False,
                request_sent_to_cloud=False,
                sensitive_data_types=privacy_check.detected_types,
            )

        started_at = time.perf_counter()
        try:
            provider_answer = self._sender(request_text, self._api_key)
        except Exception:
            cloud_latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            return CloudAdapterResult(
                answer=None,
                message=CLOUD_FAILURE_MESSAGE,
                status="cloud_request_failed",
                processed=False,
                request_sent_to_cloud=True,
                cloud_latency_ms=cloud_latency_ms,
                sensitive_data_types=privacy_check.detected_types,
            )

        if not isinstance(provider_answer, str) or not provider_answer.strip():
            cloud_latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            return CloudAdapterResult(
                answer=None,
                message=CLOUD_FAILURE_MESSAGE,
                status="cloud_request_failed",
                processed=False,
                request_sent_to_cloud=True,
                cloud_latency_ms=cloud_latency_ms,
                sensitive_data_types=privacy_check.detected_types,
            )

        cloud_latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        return CloudAdapterResult(
            answer=provider_answer.strip(),
            message=None,
            status="completed",
            processed=True,
            request_sent_to_cloud=True,
            cloud_latency_ms=cloud_latency_ms,
            sensitive_data_types=privacy_check.detected_types,
        )
