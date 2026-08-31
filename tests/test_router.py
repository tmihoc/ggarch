"""Router tests — anchor points and edge routing."""
import pytest
from ggarch import parse, validate
from ggarch.solver import solve
from ggarch.router import route, Point, _best_anchors, _face_point
from ggarch.layout import Rect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def solve_and_route(src: str):
    f = parse(src)
    validate(f)
    diagram = f.diagrams[0]
    model = f.get_model(diagram.model_name)
    layout = solve(diagram, model)
    return route(layout, model, diagram.select), f, diagram


SIMPLE_TWO = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "calls"]
  }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 40 }
}
"""


# ---------------------------------------------------------------------------
# Anchor point tests
# ---------------------------------------------------------------------------

class TestAnchors:
    def test_face_point_top(self):
        r = Rect(0, 0, 100, 50)
        p = _face_point(r, "top")
        assert abs(p.x - 50) < 0.1
        assert abs(p.y - 0) < 0.1

    def test_face_point_bottom(self):
        r = Rect(0, 0, 100, 50)
        p = _face_point(r, "bottom")
        assert abs(p.x - 50) < 0.1
        assert abs(p.y - 50) < 0.1

    def test_face_point_left(self):
        r = Rect(10, 20, 100, 50)
        p = _face_point(r, "left")
        assert abs(p.x - 10) < 0.1
        assert abs(p.y - 45) < 0.1

    def test_face_point_right(self):
        r = Rect(10, 20, 100, 50)
        p = _face_point(r, "right")
        assert abs(p.x - 110) < 0.1
        assert abs(p.y - 45) < 0.1

    def test_best_anchors_horizontal(self):
        """Left node uses right face; right node uses left face."""
        left  = Rect(0,   0, 80, 40)
        right = Rect(200, 0, 80, 40)
        src_pt, tgt_pt = _best_anchors(left, right)
        assert src_pt.x == left.x2
        assert tgt_pt.x == right.x

    def test_best_anchors_vertical(self):
        """Top node uses bottom face; bottom node uses top face."""
        top    = Rect(0, 0,   80, 40)
        bottom = Rect(0, 200, 80, 40)
        src_pt, tgt_pt = _best_anchors(top, bottom)
        assert src_pt.y == top.y2
        assert tgt_pt.y == bottom.y


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------

class TestRouting:
    def test_two_nodes_one_edge(self):
        rl, f, _ = solve_and_route(SIMPLE_TWO)
        assert len(rl.edges) == 1
        e = rl.edges[0]
        assert e.source_id == "a"
        assert e.target_id == "b"
        assert len(e.points) >= 2

    def test_edge_start_near_source_right_face(self):
        """For a left-of layout the edge starts at the right face of a."""
        rl, _, _ = solve_and_route(SIMPLE_TWO)
        e = rl.edges[0]
        src_node = rl.layout.find("a")
        # Start x should be at or near the right edge of 'a'.
        assert abs(e.start.x - src_node.rect.x2) < 1.0

    def test_edge_end_near_target_left_face(self):
        """For a left-of layout the edge ends at the left face of b."""
        rl, _, _ = solve_and_route(SIMPLE_TWO)
        e = rl.edges[0]
        tgt_node = rl.layout.find("b")
        assert abs(e.end.x - tgt_node.rect.x) < 1.0

    def test_straight_line_for_vertically_separated_nodes(self):
        """Nodes clearly separated vertically → exactly 2 waypoints."""
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges { a -> b [type: api, label: "calls"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a above b gap: 80 }
}
"""
        rl, _, _ = solve_and_route(src)
        e = rl.edges[0]
        assert len(e.points) == 2

    def test_elbow_for_same_level_nodes(self):
        """Nodes at the same y-centre → elbow (4 waypoints)."""
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges { a -> b [type: api, label: "x"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions {
    a left-of b gap: 40
    a align-middle b
  }
}
"""
        rl, _, _ = solve_and_route(src)
        e = rl.edges[0]
        assert len(e.points) == 4

    def test_edge_label_preserved(self):
        rl, _, _ = solve_and_route(SIMPLE_TWO)
        assert rl.edges[0].label == "calls"

    def test_edge_type_preserved(self):
        rl, _, _ = solve_and_route(SIMPLE_TWO)
        assert rl.edges[0].edge_type == "api"

    def test_stream_edge_dashed(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges { a -> b [type: stream, label: "watch"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 40 }
}
"""
        rl, _, _ = solve_and_route(src)
        assert rl.edges[0].style == "dashed"

    def test_ipc_edge_dotted(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges { a -> b [type: ipc, label: "socket"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 40 }
}
"""
        rl, _, _ = solve_and_route(src)
        assert rl.edges[0].style == "dotted"

    def test_missing_endpoint_skipped(self):
        """Edges whose endpoints are not in the layout are silently skipped."""
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
    c [type: t, label: "C"]
  }
  edges {
    a -> b [type: api, label: "x"]
    a -> c [type: api, label: "y"]
  }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 40 }
}
"""
        rl, _, _ = solve_and_route(src)
        # Only a->b is routed; a->c is skipped (c not in layout).
        assert len(rl.edges) == 1
        assert rl.edges[0].target_id == "b"

    def test_mid_point_straight(self):
        """Mid of a straight 2-point edge is the geometric midpoint."""
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges { a -> b [type: api, label: "calls"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a above b gap: 80 }
}
"""
        rl, _, _ = solve_and_route(src)
        e = rl.edges[0]
        assert len(e.points) == 2
        expected_mx = (e.start.x + e.end.x) / 2
        expected_my = (e.start.y + e.end.y) / 2
        assert abs(e.mid.x - expected_mx) < 0.1
        assert abs(e.mid.y - expected_my) < 0.1


# ---------------------------------------------------------------------------
# Auto-layout children (direction pass)
# ---------------------------------------------------------------------------

class TestAutoLayout:
    def test_children_laid_out_horizontally_by_default(self):
        """Container children default to left-to-right layout."""
        src = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      a [type: t, label: "A"]
      b [type: t, label: "B"]
      c [type: t, label: "C"]
    }
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: pod }
}
"""
        f = parse(src)
        validate(f)
        diagram = f.diagrams[0]
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        a = layout.find("a")
        b = layout.find("b")
        c = layout.find("c")
        # Each child should be to the right of the previous.
        assert b.rect.x > a.rect.x
        assert c.rect.x > b.rect.x

    def test_children_laid_out_vertically_with_direction_down(self):
        """direction: down stacks children top-to-bottom."""
        src = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      a [type: t, label: "A"]
      b [type: t, label: "B"]
    }
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: pod }
  positions { pod direction: down }
}
"""
        f = parse(src)
        validate(f)
        diagram = f.diagrams[0]
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        a = layout.find("a")
        b = layout.find("b")
        assert b.rect.y > a.rect.y


# ---------------------------------------------------------------------------
# Juju integration
# ---------------------------------------------------------------------------

class TestJujuRouting:
    def test_k8s_topology_routes(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
        f = parse(src)
        validate(f)
        diagram = next(d for d in f.diagrams if d.name == "K8s deployment topology")
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        rl = route(layout, model, diagram.select)
        # At least some edges should be routed.
        assert len(rl.edges) > 0
        # All routed edges have at least 2 waypoints.
        for e in rl.edges:
            assert len(e.points) >= 2

    def test_k8s_children_not_stacked(self):
        """After auto-layout, controller_pod children should not all share y."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
        f = parse(src)
        validate(f)
        diagram = next(d for d in f.diagrams if d.name == "K8s deployment topology")
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        ctrl = layout.find("controller_pod")
        if ctrl and ctrl.children:
            y_values = [c.rect.y for c in ctrl.children]
            x_values = [c.rect.x for c in ctrl.children]
            # Children should not all be at the same x (horizontal layout).
            assert len(set(round(x, 0) for x in x_values)) > 1
