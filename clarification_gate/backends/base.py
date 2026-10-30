from typing import Protocol


class UnsupportedInput(ValueError):
    """A backend cannot faithfully represent this request; never guess a decision."""


class PredictorBackend(Protocol):
    reference: dict

    def assess(self, snapshot: dict) -> dict:
        """Return a gate.v1 Assessment with field IDs, never execute a task."""
        ...

    def close(self) -> None: ...
