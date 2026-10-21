"""context: — the view-level type override (view-relative context records).

"Whose page is this" is a fact about the view, not the model: the same
record is a page's own subject on its page and another page's context
elsewhere. `context: a b` in a diagram's select marks those nodes as
context records for that view; the model keeps one page-agnostic type.
"""
import pytest

from ggarch.parser import parse
from ggarch.validator import ValidationError, validate

SRC = '''
model "S" {
  nodes {
    parent [type: record, label: "Parent"] { fields { uuid [label: "uuid", type: "text", pk: true] } }
    child  [type: record, label: "Child"] { fields {
      id [label: "id", type: "int", pk: true]
      parent_uuid [label: "parent_uuid", type: "text", fk: true] } }
  }
  edges { child.parent_uuid -> parent.uuid [type: data] }
  style { extends: juju }
}
diagram "Plain" from "S" {
  select { nodes: parent child
           edges: type data
           fields: hidden }
  positions { child right-of parent gap: 60
              child align-middle parent }
}
diagram "WithContext" from "S" {
  select { nodes: parent child
           context: parent
           edges: type data
           fields: hidden }
  positions { child right-of parent gap: 60
              child align-middle parent }
}
'''


def test_context_parses_into_the_select():
    f = parse(SRC)
    assert f.diagrams[0].select.context_nodes == []
    assert f.diagrams[1].select.context_nodes == ["parent"]

def test_context_node_must_be_selected():
    bad = SRC.replace("context: parent", "context: ghost")
    f = parse(bad)
    with pytest.raises(ValidationError, match="context node 'ghost'"):
        validate(f)


def test_context_renders_differently_than_the_model_type():
    from ggarch.solver import solve
    from ggarch.router import route
    from ggarch.renderer import render
    f = parse(SRC)
    validate(f)
    out = {}
    for name in ("Plain", "WithContext"):
        d = next(x for x in f.diagrams if x.name == name)
        m = f.get_model(d.model_name)
        out[name] = render(route(solve(d, m), m, d.select), m, d)
    assert out["Plain"] != out["WithContext"], "context: must change the drawing"
