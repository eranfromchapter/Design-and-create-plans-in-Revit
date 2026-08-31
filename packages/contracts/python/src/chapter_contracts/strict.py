"""Base model for all generated contract types: unknown members are rejected (nested
additionalProperties:false in the schemas), and nothing is materialized on serialization
that was not present on parse (no-defaults rule, PLAN.md Part D)."""

from pydantic import BaseModel, ConfigDict


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
