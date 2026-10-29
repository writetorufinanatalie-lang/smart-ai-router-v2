"""Local detector for common sensitive values before any cloud handoff."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class SensitiveDataType(str, Enum):
    EMAIL = "email"
    PHONE_NUMBER = "phone_number"
    CARD_LIKE_NUMBER = "card_like_number"


@dataclass(frozen=True)
class PrivacyCheck:
    detected_types: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.detected_types)


_EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d().\s-]{8,}\d(?!\w)")


class PrivacyShield:
    """Detect email, phone, and card-like patterns without retaining their values."""

    def inspect(self, text: str) -> PrivacyCheck:
        if not isinstance(text, str) or not text:
            return PrivacyCheck(())

        found: list[SensitiveDataType] = []
        card_spans: list[tuple[int, int]] = []

        if _EMAIL_PATTERN.search(text):
            found.append(SensitiveDataType.EMAIL)

        for match in _CARD_PATTERN.finditer(text):
            digit_count = sum(character.isdigit() for character in match.group())
            if 13 <= digit_count <= 19:
                card_spans.append(match.span())
        if card_spans:
            found.append(SensitiveDataType.CARD_LIKE_NUMBER)

        phone_found = False
        for match in _PHONE_PATTERN.finditer(text):
            digit_count = sum(character.isdigit() for character in match.group())
            overlaps_card = any(
                match.start() < card_end and match.end() > card_start
                for card_start, card_end in card_spans
            )
            if 10 <= digit_count <= 15 and not overlaps_card:
                phone_found = True
                break
        if phone_found:
            found.append(SensitiveDataType.PHONE_NUMBER)

        return PrivacyCheck(tuple(data_type.value for data_type in found))
