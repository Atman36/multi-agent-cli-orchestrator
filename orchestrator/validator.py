from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class SchemaValidationError(ValueError):
    pass


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_json(instance: dict[str, Any], schema_path: Path) -> None:
    schema = _load_schema(schema_path)
    v = Draft202012Validator(schema)
    errors = sorted(v.iter_errors(instance), key=lambda e: e.path)
    if errors:
        msg_lines = [f"Schema validation failed for {schema_path}:"]
        for e in errors[:10]:
            loc = "/".join([str(p) for p in e.path]) or "<root>"
            msg_lines.append(f"- {loc}: {e.message}")
        raise SchemaValidationError("\n".join(msg_lines))
