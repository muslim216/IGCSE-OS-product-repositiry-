"""The committed OpenAPI snapshot must match the app that produced it.

Task 0.8 replaced the frontend's hand-mirrored TypeScript interfaces with
types generated from `frontend/openapi.json`. That closes RISK-6 only while
the snapshot is current: a generated file nothing regenerates is a
hand-maintained file with extra steps, and the failure it is meant to prevent
— backend response shape changes, frontend keeps compiling against the old
one — comes back unchanged and now looks verified.

So this is the check that the snapshot is not stale. It fails on any endpoint
added, removed or reshaped without regenerating, and the fix is two commands:

    python -c "import json;from app.main import app;print(json.dumps(app.openapi(),indent=2))" \
        > ../frontend/openapi.json
    cd ../frontend && npm run generate:api

The second half — schema.d.ts actually matching openapi.json — is checked in
CI's frontend job, which regenerates it and fails on a diff. Both halves are
needed: this test alone would let a fresh openapi.json sit beside stale
TypeScript.
"""

import json
import pathlib

from app.main import app

SNAPSHOT = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend" / "openapi.json"

REGENERATE = (
    "Regenerate it: from backend/, "
    'python -c "import json;from app.main import app;print(json.dumps(app.openapi(),indent=2))"'
    " > ../frontend/openapi.json && cd ../frontend && npm run generate:api"
)


def test_the_committed_openapi_snapshot_is_current():
    assert SNAPSHOT.exists(), f"{SNAPSHOT} is missing — the frontend types generate from it."
    snapshot = json.loads(SNAPSHOT.read_text())
    # Round-tripped through JSON because app.openapi() returns Python objects
    # (tuples, enum members) that compare unequal to their serialized form even
    # when the document is identical.
    live = json.loads(json.dumps(app.openapi()))

    live_paths, snapshot_paths = set(live["paths"]), set(snapshot["paths"])
    assert live_paths == snapshot_paths, (
        f"openapi.json is stale. Missing from the snapshot: {sorted(live_paths - snapshot_paths)}. "
        f"No longer served: {sorted(snapshot_paths - live_paths)}. {REGENERATE}"
    )

    live_schemas = live.get("components", {}).get("schemas", {})
    snapshot_schemas = snapshot.get("components", {}).get("schemas", {})
    # Named separately from the whole-document assert below because a changed
    # response model is the case FE-4 is about, and "these three schemas
    # differ" is a usable message where a 12,000-line dict diff is not.
    changed = sorted(
        name
        for name in set(live_schemas) | set(snapshot_schemas)
        if live_schemas.get(name) != snapshot_schemas.get(name)
    )
    assert not changed, f"Schemas differ from the snapshot: {changed}. {REGENERATE}"

    assert live == snapshot, f"openapi.json differs from the live document. {REGENERATE}"
