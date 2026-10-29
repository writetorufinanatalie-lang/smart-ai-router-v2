"""Small deterministic fallbacks for contradictory or ambiguous requests."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ClarificationRequest:
    message: str
    reason: str


_BRIEFNESS = re.compile(r"\b(?:brief(?:ly)?|short|concise)\b", re.IGNORECASE)
_EXHAUSTIVENESS = re.compile(
    r"\b(?:every|all|complete|comprehensive|exhaustive)\b", re.IGNORECASE
)
_DETAIL = re.compile(r"\b(?:technical\s+)?details?\b", re.IGNORECASE)


def detect_ambiguity(request_text: str) -> ClarificationRequest | None:
    """Ask before routing when a request simultaneously asks for brevity and exhaustiveness."""

    if (
        _BRIEFNESS.search(request_text)
        and _EXHAUSTIVENESS.search(request_text)
        and _DETAIL.search(request_text)
    ):
        return ClarificationRequest(
            message=(
                "Your request asks for both a brief answer and exhaustive detail. "
                "Which should I prioritize?"
            ),
            reason="conflicting brevity and detail requirements",
        )
    return None
