"""Every structured-output model must be a schema the provider will accept.

Anthropic refuses a schema whose definitions refer to themselves, directly or
through another definition ("Circular reference detected in schema
definitions"). It refuses it at request time, so a recursive model fails every
call on that surface while the suite stays green: `fake_ai` replaces
`structured_complete` and never builds the schema at all. That is how
`ExtractedTopic.children: list[ExtractedTopic]` failed every syllabus upload
(T-025).

So the models are found by reading the source, not from a hand-kept list, and
each is put through `ai._json_schema_format` — the schema actually sent, after
the SDK's own transform. This covers the Anthropic path only: the Gemini path
is handed the class itself and builds its own schema, which this does not see.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.services.ai import _json_schema_format

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# Nine distinct models at ten call sites when this was written. A lower count
# means the search stopped finding them, not that the code got smaller, and a
# guard that checks nothing passes silently.
MIN_MODELS = 9


def _output_format_keywords(source: str, filename: str) -> tuple[set[str], list[str]]:
    """The names passed as `output_format=` in one file, and `file:line` for
    every `output_format=` whose value is anything but a bare name. Those are
    reported rather than skipped: `output_format=module.Model` would otherwise
    leave its model unchecked with nothing to say so."""
    names: set[str] = set()
    unreadable: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "output_format":
                continue
            if isinstance(keyword.value, ast.Name):
                names.add(keyword.value.id)
            else:
                unreadable.append(f"{filename}:{keyword.value.lineno}")
    return names, unreadable


UNREADABLE: list[str] = []


def _output_format_models() -> dict[str, type[BaseModel]]:
    """`module:Name` -> the class, for every `output_format=<Name>` keyword in
    `app/`. Resolved by importing the calling module, so a model imported from
    elsewhere is found under the name the call site uses."""
    found: dict[str, type[BaseModel]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        names, unreadable = _output_format_keywords(
            path.read_text(), str(path.relative_to(APP_DIR.parent))
        )
        UNREADABLE.extend(unreadable)
        if not names:
            continue
        module_name = ".".join(path.relative_to(APP_DIR.parent).with_suffix("").parts)
        module = importlib.import_module(module_name)
        for name in sorted(names):
            model = getattr(module, name)
            not_a_model = (
                f"{module_name}:{name} is passed as output_format but is not a Pydantic model"
            )
            # Two asserts, in this order: issubclass raises on a non-class
            # rather than failing with the message.
            assert isinstance(model, type), not_a_model
            assert issubclass(model, BaseModel), not_a_model
            found[f"{module_name}:{name}"] = model
    return found


def _refs(node: object) -> set[str]:
    """Every `$ref` target inside one schema node, without following them."""
    out: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            out.add(ref)
        for key, value in node.items():
            if key != "$defs":
                out |= _refs(value)
    elif isinstance(node, list):
        for item in node:
            out |= _refs(item)
    return out


def _ref_cycle(schema: dict) -> list[str] | None:
    """A cycle in the graph of `$ref`s between definitions, as the path that
    closes it, or None. The root is a node too (`#`), so a root that refers to
    itself is caught. A plain, acyclic `$ref` is fine — the provider accepts
    shared definitions, only recursion is refused."""
    root = "#"
    graph: dict[str, set[str]] = {root: _refs(schema)}
    for name, definition in schema.get("$defs", {}).items():
        graph[f"#/$defs/{name}"] = _refs(definition)

    visiting: list[str] = []
    done: set[str] = set()

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            return [*visiting[visiting.index(node) :], node]
        if node in done:
            return None
        visiting.append(node)
        for target in sorted(graph.get(node, ())):
            cycle = visit(target)
            if cycle:
                return cycle
        visiting.pop()
        done.add(node)
        return None

    for node in graph:
        cycle = visit(node)
        if cycle:
            return cycle
    return None


MODELS = _output_format_models()


def test_the_search_finds_every_output_format_model():
    assert len(MODELS) >= MIN_MODELS, sorted(MODELS)


def test_every_output_format_is_a_name_the_search_can_resolve():
    assert UNREADABLE == [], (
        "output_format= must be passed a bare model name so this guard can check it; "
        f"rewrite these call sites: {', '.join(UNREADABLE)}"
    )


def test_the_search_reports_an_output_format_it_cannot_resolve():
    """The check above is only worth something if it can fail."""
    source = "structured_complete(output_format=schemas.Model)\nother(output_format=Model)\n"
    names, unreadable = _output_format_keywords(source, "snippet.py")
    assert names == {"Model"}
    assert unreadable == ["snippet.py:1"]


@pytest.mark.parametrize("where", sorted(MODELS))
def test_output_format_schema_has_no_circular_reference(where):
    schema = _json_schema_format(MODELS[where])["format"]["schema"]
    cycle = _ref_cycle(schema)
    assert cycle is None, f"{where} sends a self-referencing schema: {' -> '.join(cycle)}"


def test_the_cycle_check_catches_recursion():
    """The check above is only worth something if it can fail."""

    class Node(BaseModel):
        name: str
        children: list[Node] = []

    class Wrapper(BaseModel):
        nodes: list[Node]

    assert _ref_cycle(_json_schema_format(Wrapper)["format"]["schema"]) is not None
    assert _ref_cycle(_json_schema_format(Node)["format"]["schema"]) is not None
