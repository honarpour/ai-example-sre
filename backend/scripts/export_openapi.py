"""Dump the FastAPI OpenAPI schema to a file without booting a server.

Used by `make types` so the frontend's generated TS types never drift from the
Pydantic models in app/models/domain.py.

Pydantic marks a field with a default (including `default_factory`) as NOT
required in its JSON Schema, even though every one of our response models
always populates that field server-side — `Investigation.evidence` has
`default_factory=list`, but a real API response never omits it. Left alone,
openapi-typescript turns every such field into `T | undefined`, cascading
`possibly undefined` errors through every component that touches them for no
real benefit (the frontend never receives a response missing these fields).
We force every property on our response-only schemas to be `required` here,
at the single point where the OpenAPI contract is generated, rather than
sprinkling `!` assertions or optional chaining across the UI. Request-body
schemas are deliberately left alone — there, "has a default" genuinely means
"the client may omit this".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

# Schemas that only ever appear in API *responses*. Everything else (request
# bodies) keeps Pydantic's real optionality.
RESPONSE_ONLY_SCHEMAS = {
    "Alert",
    "Investigation",
    "AgentStep",
    "Evidence",
    "Hypothesis",
    "SuggestedAction",
    "ScenarioSummary",
    "StreamEvent",
    "AskFollowUpResponse",
}


def force_required(schema: dict[str, Any]) -> None:
    components = schema.get("components", {}).get("schemas", {})
    for name in RESPONSE_ONLY_SCHEMAS:
        definition = components.get(name)
        if definition and "properties" in definition:
            definition["required"] = list(definition["properties"].keys())


if __name__ == "__main__":
    schema = app.openapi()
    force_required(schema)
    out_path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "openapi.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(schema, indent=2))
    print(f"wrote {out_path}")
