"""Port-semantics tests for border notches (ADR-003 decision 11).

A container border is notched only where an edge genuinely enters or
exits the subtree — exactly one endpoint inside. Edges passing OVER a
container (both endpoints outside) leave the border solid; internal
edges do not notch their own container. Annotation boxes never notch
(a circling has no gates).
"""
from ggarch.layout import Rect, SolvedLayout, SolvedNode
from ggarch.renderer import _compute_border_gaps
from ggarch.router import Point, RoutedEdge


def make_layout():
    """Container c (child x) with a and b outside; a passes over c."""
    a = SolvedNode(id="a", rect=Rect(0, 0, 60, 30))
    b = SolvedNode(id="b", rect=Rect(300, 0, 60, 30))
    x = SolvedNode(id="x", rect=Rect(140, 10, 40, 20))
    c = SolvedNode(id="c", rect=Rect(120, 0, 100, 60), children=[x])
    return SolvedLayout(nodes=[a, b, c])


def edge(src, tgt, points):
    return RoutedEdge(
        source_id=src, target_id=tgt, label="", edge_type="api",
        style="solid", arrow="forward",
        points=[Point(px, py) for px, py in points])


class TestBorderGaps:
    def test_entering_edge_notches_the_container(self):
        """One endpoint inside: the crossing is a port — notched."""
        layout = make_layout()
        e = edge("a", "x", [(60, 15), (140, 20)])  # crosses c's left wall
        gaps = _compute_border_gaps(layout.nodes, [e], 0, 0)
        assert gaps.get("c", {}).get("left"), gaps

    def test_overpassing_edge_leaves_the_border_solid(self):
        """Both endpoints outside: passing over the container is a
        routing defect, not a border feature — no notch."""
        layout = make_layout()
        e = edge("a", "b", [(60, 15), (300, 15)])  # straight through c
        gaps = _compute_border_gaps(layout.nodes, [e], 0, 0)
        assert not gaps.get("c", {}).get("left"), gaps
        assert not gaps.get("c", {}).get("right"), gaps

    def test_internal_edge_does_not_notch_its_own_container(self):
        """Both endpoints inside: internal wiring — no notch."""
        layout = make_layout()
        x2 = SolvedNode(id="x2", rect=Rect(140, 10, 40, 20))
        # Build a second child inside c.
        c = layout.find("c")
        c.children.append(SolvedNode(id="y", rect=Rect(170, 30, 30, 20)))
        e = edge("x", "y", [(180, 20), (180, 30)])  # inside c only
        gaps = _compute_border_gaps(layout.nodes, [e], 0, 0)
        assert not any(gaps.get("c", {}).values()), gaps


# ---------------------------------------------------------------------------
# Annotation boxes never notch (a circling has no gates)
# ---------------------------------------------------------------------------

from ggarch import parse, validate as _validate
from ggarch.solver import solve
from ggarch.router import route
from ggarch.renderer import render


def _pipeline(src, dark=False):
    f = parse(src)
    _validate(f)
    diagram = f.diagrams[0]
    model = f.get_model(diagram.model_name)
    layout = solve(diagram, model)
    rl = route(layout, model, diagram.select)
    return render(rl, model, diagram, dark=dark)


ANN_SRC = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
    c [type: t, label: "C"]
  }
  edges { a -> c [type: api, label: "x"] }
}
diagram "D" from "M" {
  select { nodes: a b c }
  positions {
    a left-of b gap: 40
    b left-of c gap: 40
    a align-middle b
    b align-middle c
  }
  annotations {
    box [nodes: "a b", label: "region", color: "#E95420"]
  }
}
"""


class TestAnnotationBoxes:
    def test_annotation_border_is_never_notched(self):
        """An edge leaving the circled area crosses the annotation
        border — the border stays solid (meta element, no gates)."""
        import re
        svg = _pipeline(ANN_SRC)
        # One unbroken rect border, never gap-cut path segments.
        assert re.findall(r'<rect[^>]*stroke="#E95420"', svg), (
            "annotation border missing")
        assert not re.findall(r'<path[^>]*stroke="#E95420"', svg), (
            "annotation border was drawn as gap-cut segments")
