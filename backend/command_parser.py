"""Strict rule-based parser for the router's safe simulated commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class CommandAction(str, Enum):
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    SET_BRIGHTNESS = "set_brightness"
    SET_FAN_SPEED = "set_fan_speed"
    SET_VOLUME = "set_volume"


@dataclass(frozen=True)
class ParsedCommand:
    """A command represented only by supported device/action/value fields."""

    device: str
    action: CommandAction
    value: int | None = None


@dataclass(frozen=True)
class CommandParseResult:
    """Parser outcome, distinguishing unsupported intent from ordinary text."""

    command: ParsedCommand | None
    recognized_command: bool
    reason: str | None = None
    unsupported_device: bool = False
    clarification_needed: bool = False

    @property
    def supported(self) -> bool:
        return self.command is not None


_DEVICE = r"(?P<device>desk light|lights?|fan)"
_TURN_PATTERNS = (
    re.compile(rf"(?:please )?(?:turn|switch) (?P<state>on|off) (?:the )?{_DEVICE}(?: please)?"),
    re.compile(rf"(?:please )?{_DEVICE} (?P<state>on|off)(?: please)?"),
    re.compile(rf"(?:please )?(?:turn|switch) (?:the )?{_DEVICE} (?P<state>on|off)(?: please)?"),
    re.compile(rf"(?:please )?(?:power|activate|enable) (?:up )?(?:the )?{_DEVICE}(?: please)?"),
    re.compile(rf"(?:please )?(?:power down|power off|deactivate|disable|shut off) (?:the )?{_DEVICE}(?: please)?"),
)
_LEVEL_PATTERNS = (
    (
        re.compile(
            r"(?:please )?set (?:the )?(?P<device>desk light|light) brightness"
            r"(?: to)? (?P<value>-?\d{1,3})(?: ?(?:%|percent))?(?: please)?"
        ),
        "brightness",
    ),
    (
        re.compile(
            r"(?:please )?set brightness (?:of )?(?:(?:the|my) )?(?P<device>desk light|light)"
            r"(?: to)? (?P<value>-?\d{1,3})(?: ?(?:%|percent))?(?: please)?"
        ),
        "brightness",
    ),
    (
        re.compile(
            r"(?:please )?(?:dim|brighten) (?:the )?(?P<device>desk light|light)"
            r"(?: to)? (?P<value>-?\d{1,3})(?: ?(?:%|percent))?(?: please)?"
        ),
        "brightness",
    ),
    (
        re.compile(
            r"(?:please )?make (?:the )?(?P<device>desk light|light)"
            r"(?: brighter| dimmer) to (?P<value>-?\d{1,3})"
            r"(?: ?(?:%|percent))?(?: please)?"
        ),
        "brightness",
    ),
    (
        re.compile(
            r"(?:please )?set (?:the )?fan speed(?: to)? "
            r"(?P<value>-?\d{1,3})(?: ?(?:%|percent))?(?: please)?"
        ),
        "fan_speed",
    ),
    (
        re.compile(
            r"(?:please )?(?:put|set) (?:the )?fan speed (?:at|to) "
            r"(?P<value>-?\d{1,3})(?: ?(?:%|percent))?(?: please)?"
        ),
        "fan_speed",
    ),
    (
        re.compile(
            r"(?:please )?run (?:the )?fan at "
            r"(?P<value>-?\d{1,3})(?: ?(?:%|percent))?(?: please)?"
        ),
        "fan_speed",
    ),
    (
        re.compile(
            r"(?:please )?set (?:the )?volume(?: to)? "
            r"(?P<value>-?\d{1,3})(?: ?(?:%|percent))?(?: please)?"
        ),
        "volume",
    ),
    (
        re.compile(
            r"(?:please )?set (?:the )?sound volume(?: to)? "
            r"(?P<value>-?\d{1,3})(?: ?(?:%|percent))?(?: please)?"
        ),
        "volume",
    ),
    (
        re.compile(
            r"(?:please )?(?:raise|lower) (?:the )?volume to "
            r"(?P<value>-?\d{1,3})(?: ?(?:%|percent))?(?: please)?"
        ),
        "volume",
    ),
)
_UNKNOWN_DEVICE_ON_OFF = re.compile(
    r"(?:please )?(?:turn|switch) (?:on|off) (?:(?:the|my) )?"
    r"(?P<device>(?:[a-z0-9'-]+ )+(?:light|fan))(?: please)?"
)


def _canonical_device(value: str) -> str:
    return "desk_light" if value in {"light", "lights", "desk light"} else value


_SUPPORTED_DEVICE_MENTION = re.compile(r"\b(?:desk light|lights?|fan|volume)\b")
_CONTROL_VERB = re.compile(
    r"\b(?:turn|switch|power|activate|enable|deactivate|disable|shut off|set|"
    r"adjust|dim|brighten|make|put|run|raise|lower|increase|decrease)\b"
)
_CONTROL_STATE = re.compile(r"\b(?:on|off)\b")
_NEGATION = re.compile(r"\b(?:do not|don't|never|cannot|can't|won't|shouldn't|mustn't)\b")
_CONDITIONAL = re.compile(r"\b(?:if|unless|when|whenever|once|before|after)\b")
_QUESTION_START = re.compile(
    r"^(?:how|what|why|when|where|who|can|could|would|should|do|does|did)\b"
)


def _clarification_reason(text: str, normalized: str) -> str | None:
    """Reject unsafe or unclear command-like text before any whitelist match."""

    has_control_cue = _CONTROL_VERB.search(normalized) or _CONTROL_STATE.search(normalized)
    if not _SUPPORTED_DEVICE_MENTION.search(normalized) or not has_control_cue:
        return None

    if "?" in text or _QUESTION_START.search(normalized):
        return "question about device control needs clarification"
    if _NEGATION.search(normalized):
        return "negated device command needs clarification"
    if _CONDITIONAL.search(normalized):
        return "conditional device command needs clarification"

    device_mentions = _SUPPORTED_DEVICE_MENTION.findall(normalized)
    control_verbs = _CONTROL_VERB.findall(normalized)
    state_mentions = _CONTROL_STATE.findall(normalized)
    numeric_values = re.findall(r"(?<!\w)-?\d+(?!\w)", normalized)
    if (
        len(device_mentions) > 1
        or len(control_verbs) > 1
        or len(state_mentions) > 1
        or len(numeric_values) > 1
    ):
        return "multiple device commands need clarification"
    return None


def parse_command(text: str) -> CommandParseResult:
    """Parse only the explicitly supported command forms; never infer actions."""

    if not isinstance(text, str) or not text.strip():
        return CommandParseResult(None, False, "empty request")

    normalized = " ".join(text.casefold().strip().split())
    clarification_reason = _clarification_reason(text, normalized)
    if clarification_reason:
        return CommandParseResult(
            None,
            False,
            clarification_reason,
            clarification_needed=True,
        )

    normalized = normalized.rstrip(".!?").strip()

    if _SUPPORTED_DEVICE_MENTION.search(normalized) and (
        _CONTROL_VERB.search(normalized) or _CONTROL_STATE.search(normalized)
    ):
        # Any command-like sentence that fails a whole-string whitelist pattern
        # stays non-executable and asks the user to clarify its intent.
        unmatched_command_like = True
    else:
        unmatched_command_like = False

    for pattern in _TURN_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match:
            device = _canonical_device(match.group("device"))
            state = match.groupdict().get("state")
            action = (
                CommandAction.TURN_OFF
                if state == "off" or (state is None and pattern is _TURN_PATTERNS[-1])
                else CommandAction.TURN_ON
            )
            if device == "volume":
                return CommandParseResult(None, True, "volume does not support on/off")
            return CommandParseResult(ParsedCommand(device, action), True)

    for pattern, kind in _LEVEL_PATTERNS:
        match = pattern.fullmatch(normalized)
        if not match:
            continue

        value = int(match.group("value"))
        if not 0 <= value <= 100:
            return CommandParseResult(
                None,
                True,
                f"{kind.replace('_', ' ')} must be between 0 and 100",
            )

        if kind == "brightness":
            command = ParsedCommand(
                _canonical_device(match.group("device")),
                CommandAction.SET_BRIGHTNESS,
                value,
            )
        elif kind == "fan_speed":
            command = ParsedCommand("fan", CommandAction.SET_FAN_SPEED, value)
        else:
            command = ParsedCommand("volume", CommandAction.SET_VOLUME, value)
        return CommandParseResult(command, True)

    unknown_device = _UNKNOWN_DEVICE_ON_OFF.fullmatch(normalized)
    if unknown_device:
        device = unknown_device.group("device")
        if device not in {"desk light", "light", "fan"}:
            return CommandParseResult(
                None,
                True,
                "device not supported",
                unsupported_device=True,
            )
        return CommandParseResult(None, True, "command form not supported")

    if unmatched_command_like:
        return CommandParseResult(
            None,
            False,
            "command did not match a complete supported pattern",
            clarification_needed=True,
        )
    return CommandParseResult(None, False, "no whitelisted command pattern matched")
