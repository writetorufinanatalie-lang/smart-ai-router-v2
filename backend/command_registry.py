"""Safe in-memory simulation for commands accepted by the whitelist parser."""

from __future__ import annotations

from dataclasses import dataclass

from backend.command_parser import CommandAction, ParsedCommand


class UnsupportedCommandError(ValueError):
    """Raised if code attempts to execute a command outside the safe registry."""


@dataclass(frozen=True)
class CommandExecutionResult:
    device: str
    action: str
    message: str
    state: dict[str, int | bool]


class SimulatedDeviceRegistry:
    """A small simulated device registry; it never calls the operating system."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, int | bool]] = {
            "desk_light": {"on": False, "brightness": 50},
            "fan": {"on": False, "speed": 50},
            "volume": {"level": 50},
        }

    def snapshot(self) -> dict[str, dict[str, int | bool]]:
        """Return a copy so callers cannot mutate registry state directly."""

        return {device: dict(state) for device, state in self._state.items()}

    def execute(self, command: ParsedCommand) -> CommandExecutionResult:
        """Execute a parsed command after independently checking its whitelist."""

        if not isinstance(command, ParsedCommand):
            raise UnsupportedCommandError("command not supported")

        state = self._state.get(command.device)
        if state is None:
            raise UnsupportedCommandError("command not supported")

        if command.action in {CommandAction.TURN_ON, CommandAction.TURN_OFF}:
            if command.device not in {"desk_light", "fan"} or command.value is not None:
                raise UnsupportedCommandError("command not supported")
            state["on"] = command.action is CommandAction.TURN_ON
            message = f"{command.device.replace('_', ' ')} turned {'on' if state['on'] else 'off'}"
        elif command.action is CommandAction.SET_BRIGHTNESS:
            value = self._validated_level(command, expected_device="desk_light")
            state["brightness"] = value
            state["on"] = value > 0
            message = f"desk light brightness set to {value}%"
        elif command.action is CommandAction.SET_FAN_SPEED:
            value = self._validated_level(command, expected_device="fan")
            state["speed"] = value
            state["on"] = value > 0
            message = f"fan speed set to {value}%"
        elif command.action is CommandAction.SET_VOLUME:
            value = self._validated_level(command, expected_device="volume")
            state["level"] = value
            message = f"volume set to {value}%"
        else:
            raise UnsupportedCommandError("command not supported")

        return CommandExecutionResult(
            device=command.device,
            action=command.action.value,
            message=message,
            state=dict(state),
        )

    @staticmethod
    def _validated_level(command: ParsedCommand, *, expected_device: str) -> int:
        if (
            command.device != expected_device
            or not isinstance(command.value, int)
            or not 0 <= command.value <= 100
        ):
            raise UnsupportedCommandError("command not supported")
        return command.value
