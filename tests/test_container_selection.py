"""A view can draw a container around only some of its children, and lay
out a container's children itself (2026-11-27).

- Selecting a container and one of its descendants draws the container
  holding just that descendant (the offering model around the offer
  alone), not the container's whole subtree plus a second copy of the
  descendant.
- A view that positions a container's children against each other (a
  fan stacking two of them in one column) owns that container's layout;
  the default left-to-right placement of children does not override it.
"""
from ggarch import parse, validate
from ggarch.solver import solve

MODEL = """
model "Z" {
  nodes {
    left [type: entity, label: "Left"] {
      kept    [type: entity, label: "Kept"]
      dropped [type: entity, label: "Dropped"]
    }
    right [type: entity, label: "Right"] {
      hub [type: entity, label: "Hub"]
      one [type: entity, label: "One"]
      two [type: entity, label: "Two"]
    }
  }
  edges {
    dropped -> kept [type: control, label: "into"]
    kept    -> hub  [type: control, label: "to"]
    hub     -> one  [type: control, label: "a"]
    hub     -> two  [type: control, label: "b"]
  }
}
"""

VIEW = """
diagram "v" from "Z" {
  select {
    nodes: left kept right
    edges: type control
  }
  positions {
    right right-of left gap: 60
    fan [one two] right-of hub gap: 80
  }
}
"""


def _solve():
    f = parse(MODEL + VIEW)
    validate(f)
    d = f.diagrams[0]
    return solve(d, f.get_model("Z"))


def _ids(nodes):
    out = []
    for n in nodes:
        out.append(n.id)
        out.extend(_ids(n.children))
    return out


def test_container_selected_with_a_child_draws_only_that_child():
    layout = _solve()
    assert [n.id for n in layout.nodes] == ["left", "right"]
    left = layout.nodes[0]
    assert [c.id for c in left.children] == ["kept"]
    assert _ids(layout.nodes).count("kept") == 1
    assert "dropped" not in _ids(layout.nodes)


def test_view_fan_lays_out_container_children():
    layout = _solve()
    right = layout.nodes[1]
    rects = {c.id: c.rect for c in right.children}
    # The fan stacks one and two in one column to the right of hub.
    assert rects["one"].x == rects["two"].x
    assert rects["one"].x > rects["hub"].x2
    assert rects["one"].y2 < rects["two"].y
