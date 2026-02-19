from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.validator import SchemaValidationError, validate_json


def validate_result_contract(result_obj: dict[str, Any], schema_path: Path) -> None:
    validate_json(result_obj, schema_path)


__all__ = ["SchemaValidationError", "validate_result_contract"]
