"""Cloud-route boundary that refuses to invent provider responses."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

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
        configured_key = api_key if api_key is not None else os.environ.get("CLOUD_API_KEY", "")
        self._api_key = configured_key.strip() or None
        self._sender = sender
        self._privacy_shield = privacy_shield or PrivacyShield()

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

        try:
            provider_answer = self._sender(request_text, self._api_key)
        except Exception:
            return CloudAdapterResult(
                answer=None,
                message=CLOUD_FAILURE_MESSAGE,
                status="cloud_request_failed",
                processed=False,
                request_sent_to_cloud=True,
                sensitive_data_types=privacy_check.detected_types,
            )

        if not isinstance(provider_answer, str) or not provider_answer.strip():
            return CloudAdapterResult(
                answer=None,
                message=CLOUD_FAILURE_MESSAGE,
                status="cloud_request_failed",
                processed=False,
                request_sent_to_cloud=True,
                sensitive_data_types=privacy_check.detected_types,
            )

        return CloudAdapterResult(
            answer=provider_answer.strip(),
            message=None,
            status="completed",
            processed=True,
            request_sent_to_cloud=True,
            sensitive_data_types=privacy_check.detected_types,
        )
