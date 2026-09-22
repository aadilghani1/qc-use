"""Validate model answers before they reach the action loop or report."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Jev answers are probabilities. Booleans, NaN, and values outside [0, 1] are rejected.
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]


class ChoiceAnswer(BaseModel):
    choice: str
    probabilities: dict[str, Probability]
    confidence: Probability


class NoulAnswer(BaseModel):
    noul: Probability


class ScoreAnswer(BaseModel):
    score: float = Field(ge=0, le=9, allow_inf_nan=False, strict=True)
    probabilities: dict[str, Probability]
    confidence: Probability


class TextValue(BaseModel):
    """The text helper's entire output: one field value and where it came from."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000, strict=True)
    source: Literal["goal", "persona", "fake"] = "goal"

    @field_validator("text")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("blank")
        return value


class JevResponse(BaseModel):
    """The shared response envelope for choice, noul, and score requests."""

    model: str
    answers: dict[str, object]
    usage: dict = Field(default_factory=dict)


def jev_response(result: object) -> dict:
    """Reject malformed envelopes before accessing an answer."""
    try:
        return JevResponse.model_validate(result).model_dump()
    except ValidationError:
        raise ValueError("Invalid TypeSafe response; no action executed.") from None


def validate_choice(answer, ids):
    """Require a normalized answer that selects a permitted maximum."""
    try:
        parsed = ChoiceAnswer.model_validate(answer)
        probabilities = parsed.probabilities
        valid = (
            parsed.choice in ids
            and set(probabilities) == set(ids)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[parsed.choice] >= max(probabilities.values()) - 1e-6
        )
    except (ValidationError, TypeError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer
