"""T-044: the readiness response's published contract.

The frontend's `SubjectReadiness` is generated from this schema rather than
written by hand (FE-4). That only protects the pages if the schema says what the
server really sends: every field, always, and the band and direction as their
fixed value sets rather than any string.
"""

from app.main import app


def _schema(name: str) -> dict:
    return app.openapi()["components"]["schemas"][name]


def _enum_of(prop: dict) -> set[str]:
    values: set[str] = set()
    for option in prop.get("anyOf", [prop]):
        values.update(option.get("enum", []))
    return values


def test_every_subject_readiness_field_is_always_present():
    schema = _schema("SubjectReadiness")
    assert set(schema["required"]) == set(schema["properties"])


def test_band_and_direction_are_closed_sets():
    props = _schema("SubjectReadiness")["properties"]
    assert _enum_of(props["status"]) == {"on_track", "needs_attention", "at_risk"}
    assert _enum_of(props["direction"]) == {"up", "flat", "down"}
