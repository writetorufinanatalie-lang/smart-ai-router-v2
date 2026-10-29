"""Tests for the explicit command whitelist."""

import pytest

from backend.command_parser import CommandAction, parse_command


@pytest.mark.parametrize(
    ("text", "device", "action", "value"),
    [
        ("Turn on the desk light.", "desk_light", CommandAction.TURN_ON, None),
        ("switch off the light", "desk_light", CommandAction.TURN_OFF, None),
        ("Set the desk light brightness to 40 percent", "desk_light", CommandAction.SET_BRIGHTNESS, 40),
        ("set light brightness to 0%", "desk_light", CommandAction.SET_BRIGHTNESS, 0),
        ("set the light brightness to 100%", "desk_light", CommandAction.SET_BRIGHTNESS, 100),
        ("turn on the fan", "fan", CommandAction.TURN_ON, None),
        ("fan off", "fan", CommandAction.TURN_OFF, None),
        ("set fan speed to 65%", "fan", CommandAction.SET_FAN_SPEED, 65),
        ("set fan speed to 0", "fan", CommandAction.SET_FAN_SPEED, 0),
        ("set the volume to 30 percent", "volume", CommandAction.SET_VOLUME, 30),
        ("set volume to 100", "volume", CommandAction.SET_VOLUME, 100),
    ],
)
def test_parses_whitelisted_command_forms(text, device, action, value):
    result = parse_command(text)

    assert result.recognized_command is True
    assert result.supported is True
    assert result.command.device == device
    assert result.command.action is action
    assert result.command.value == value


@pytest.mark.parametrize(
    "text",
    [
        "Turn on the bedroom light.",
        "Run notepad.",
        "Turn on the light and delete my files.",
        "Set the fan speed to 101%.",
        "Set the desk light brightness to -1%.",
        "Set volume to 101%.",
    ],
)
def test_rejects_unsupported_or_out_of_range_command(text):
    result = parse_command(text)

    assert result.supported is False
    assert result.command is None


def test_marks_out_of_range_whitelisted_intent_as_recognized_but_unsupported():
    result = parse_command("Set the desk light brightness to 101 percent.")

    assert result.recognized_command is True
    assert result.supported is False
    assert "between 0 and 100" in result.reason


def test_does_not_match_command_phrase_inside_unrelated_sentence():
    result = parse_command("Write a story about someone who turns on a light.")

    assert result.recognized_command is False
    assert result.supported is False
