"""Pydantic shapes the AI layer is allowed to return (audit section C)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FieldType = Literal["string", "number", "integer", "date", "url", "boolean"]


class ProposedField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="snake_case column name")
    type: FieldType = "string"
    required: bool = False
    evidence: str = Field(
        default="", description="A value copied from the page that supports this field"
    )


class ProposedSchema(BaseModel):
    """Reply shape for the field-proposal prompt."""

    model_config = ConfigDict(extra="ignore")

    fields: list[ProposedField] = Field(default_factory=list)
    notes: str = ""


class MappedField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requested: str
    column: str | None = None
    confidence: Literal["high", "medium", "low"] = "low"
    reason: str = ""


class FieldMappingProposal(BaseModel):
    """Reply shape for semantic field mapping."""

    model_config = ConfigDict(extra="ignore")

    mappings: list[MappedField] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)


class ExtractedRecords(BaseModel):
    """Reply shape for semantic record extraction."""

    model_config = ConfigDict(extra="ignore")

    records: list[dict[str, str | int | float | bool | None]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)


class ValidationVerdict(BaseModel):
    """Reply shape for the extraction-review prompt."""

    model_config = ConfigDict(extra="ignore")

    looks_correct: bool = False
    problems: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class VariableDescription(BaseModel):
    model_config = ConfigDict(extra="ignore")

    variable: str
    label: str = ""
    unit: str = ""
    notes: str = ""


class DataDictionaryProposal(BaseModel):
    """Reply shape for data-dictionary assistance."""

    model_config = ConfigDict(extra="ignore")

    variables: list[VariableDescription] = Field(default_factory=list)
