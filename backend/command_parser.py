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

    @property
    def supported(self) -> bool:
        return self.command is not None


_DEVICE = r"(?P<device>desk light|light|fan)"
_TURN_PATTERNS = (
    re.compile(rf"(?:please )?(?:turn|switch) (?P<state>on|off) (?:the )?{_DEVICE}(?: please)?"),
    re.compile(rf"(?:please )?{_DEVICE} (?P<state>on|off)(?: please)?"),
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
            r"(?:please )?set (?:the )?fan speed(?: to)? "
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
)
_UNKNOWN_DEVICE_ON_OFF = re.compile(
    r"(?:please )?(?:turn|switch) (?:on|off) (?:(?:the|my) )?"
    r"(?P<device>(?:[a-z0-9'-]+ )+(?:light|fan))(?: please)?"
)


def _canonical_device(value: str) -> str:
    return "desk_light" if value in {"light", "desk light"} else value


def parse_command(text: str) -> CommandParseResult:
    """Parse only the explicitly supported command forms; never infer actions."""

    if not isinstance(text, str) or not text.strip():
        return CommandParseResult(None, False, "empty request")

    normalized = " ".join(text.casefold().strip().split()).rstrip(".!?").strip()

    for pattern in _TURN_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match:
            device = _canonical_device(match.group("device"))
            action = (
                CommandAction.TURN_ON
                if match.group("state") == "on"
                else CommandAction.TURN_OFF
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

    return CommandParseResult(None, False, "no whitelisted command pattern matched")
