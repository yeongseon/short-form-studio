"""SF-55: parse an LLM response into a structured EditorCommand proposal.

parse_command_proposal takes a raw LLM string, extracts the JSON batch, and
validates every command through the shared EditorCommandModel discriminated
union (SF-48). The whole batch is rejected if the JSON is malformed, the shape is
wrong, any command is unknown/malformed, the batch is empty or over the bound, or
the declared base_revision does not match the revision the caller generated the
summary against — nothing is applied here, so untrusted model output can never
reach the Timeline unvalidated. A CommandProposal carries the base_revision so
the applier can later reject a stale batch.
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from creator_domain.exceptions import ValidationError
from creator_domain.models import EditorCommand, EditorCommandModel
from pydantic import BaseModel, ConfigDict, Field, ValidationError as PydanticValidationError

_DEFAULT_MAX_COMMANDS = 50

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class CommandProposal(BaseModel):
    """A validated batch of typed EditorCommands generated for a base revision."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    base_revision: int = Field(ge=0)
    commands: list[EditorCommand] = Field(min_length=1)


def _extract_json_object(raw: str) -> dict[str, Any]:
    fenced = _JSON_FENCE.search(raw)
    candidate = fenced.group(1) if fenced is not None else raw
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError) as error:
        # Fall back to the first balanced object substring for un-fenced prose.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            raise ValidationError("proposal is not valid JSON") from error
        try:
            parsed = json.loads(candidate[start : end + 1])
        except (json.JSONDecodeError, ValueError) as inner:
            raise ValidationError("proposal is not valid JSON") from inner
    if not isinstance(parsed, dict):
        raise ValidationError("proposal must be a JSON object")
    return parsed


def parse_command_proposal(
    raw: str,
    *,
    base_revision: int,
    max_commands: int = _DEFAULT_MAX_COMMANDS,
) -> CommandProposal:
    """Parse and fully validate an LLM command batch (nothing is applied)."""
    if max_commands < 1 or max_commands > _DEFAULT_MAX_COMMANDS:
        raise ValidationError(
            f"max_commands must be between 1 and {_DEFAULT_MAX_COMMANDS}"
        )

    payload = _extract_json_object(raw)

    raw_commands = payload.get("commands")
    if not isinstance(raw_commands, list):
        raise ValidationError("proposal.commands must be a list")
    if len(raw_commands) == 0:
        raise ValidationError("proposal has no commands")
    if len(raw_commands) > max_commands:
        raise ValidationError(
            f"proposal has {len(raw_commands)} commands, exceeding the bound of {max_commands}"
        )

    if payload.get("base_revision") != base_revision:
        raise ValidationError(
            "proposal base_revision does not match the current timeline revision"
        )

    commands: list[EditorCommand] = []
    for entry in raw_commands:
        try:
            commands.append(EditorCommandModel.model_validate(entry).command)
        except PydanticValidationError as error:
            raise ValidationError("proposal contains an invalid command") from error

    return CommandProposal(base_revision=base_revision, commands=commands)
