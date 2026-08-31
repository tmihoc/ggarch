"""Solver tests — constraint satisfaction and geometry."""
import pytest
from ggarch import parse, validate
from ggarch.solver import solve
from ggarch.errors import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def solve_src(src: str):
    f = parse(src)
    validate(f)
    diagram = f.diagrams[0]
    model = f.get_model(diagram.model_name)
    return solve(diagram, model)


SIMPLE_MODEL = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "x"]
  }
}
"""


# ---------------------------------------------------------------------------
# Basic solving
# ---------------------------------------------------------------------------

class TestBasicSolving:
    def test_two_nodes_no_constraints(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
}
"""
        layout = solve_src(src)
        assert len(layout.nodes) == 2
        for n in layout.nodes:
            assert n.rect.w > 0
            assert n.rect.h > 0

    def test_nodes_have_positive_coordinates(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
}
"""
        layout = solve_src(src)
        for n in layout.nodes:
            assert n.rect.x >= 0
            assert n.rect.y >= 0

    def test_bounds_contains_all_nodes(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
}
"""
        layout = solve_src(src)
        b = layout.bounds
        for n in layout.nodes:
            assert n.rect.x >= b.x - 0.1
            assert n.rect.y >= b.y - 0.1
            assert n.rect.x2 <= b.x2 + 0.1
            assert n.rect.y2 <= b.y2 + 0.1

    def test_find_node_by_id(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
}
"""
        layout = solve_src(src)
        assert layout.find("a") is not None
        assert layout.find("b") is not None
        assert layout.find("ghost") is None


# ---------------------------------------------------------------------------
# Cardinal constraints
# ---------------------------------------------------------------------------

class TestCardinalConstraints:
    def test_left_of(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 20 }
}
"""
        layout = solve_src(src)
        a = layout.find("a")
        b = layout.find("b")
        assert a.rect.x2 + 20 <= b.rect.x + 0.1

    def test_right_of(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
  positions { a right-of b gap: 20 }
}
"""
        layout = solve_src(src)
        a = layout.find("a")
        b = layout.find("b")
        assert a.rect.x >= b.rect.x2 + 20 - 0.1

    def test_above(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
  positions { a above b gap: 30 }
}
"""
        layout = solve_src(src)
        a = layout.find("a")
        b = layout.find("b")
        assert a.rect.y2 + 30 <= b.rect.y + 0.1

    def test_below(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
  positions { a below b gap: 30 }
}
"""
        layout = solve_src(src)
        a = layout.find("a")
        b = layout.find("b")
        assert a.rect.y >= b.rect.y2 + 30 - 0.1

    def test_default_gap_applied(self):
        """Without explicit gap, the default gap (20) is used."""
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b }
}
"""
        layout = solve_src(src)
        a = layout.find("a")
        b = layout.find("b")
        # Gap is at least the default (20px).
        assert b.rect.x >= a.rect.x2 + 20 - 0.1


# ---------------------------------------------------------------------------
# Alignment constraints
# ---------------------------------------------------------------------------

class TestAlignmentConstraints:
    def test_align_middle(self):
        """Vertical centres of a and b are equal."""
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
  positions {
    a left-of b gap: 40
    a align-middle b
  }
}
"""
        layout = solve_src(src)
        a = layout.find("a")
        b = layout.find("b")
        assert abs(a.rect.cy - b.rect.cy) < 0.5

    def test_align_centre(self):
        """Horizontal centres of a and b are equal."""
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
  positions {
    a above b gap: 40
    a align-centre b
  }
}
"""
        layout = solve_src(src)
        a = layout.find("a")
        b = layout.find("b")
        assert abs(a.rect.cx - b.rect.cx) < 0.5

    def test_align_top(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
  positions {
    a left-of b gap: 40
    a align-top b
  }
}
"""
        layout = solve_src(src)
        a = layout.find("a")
        b = layout.find("b")
        assert abs(a.rect.y - b.rect.y) < 0.5

    def test_same_width(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
  positions {
    a left-of b gap: 20
    a same-width b
  }
}
"""
        layout = solve_src(src)
        a = layout.find("a")
        b = layout.find("b")
        assert abs(a.rect.w - b.rect.w) < 0.5


# ---------------------------------------------------------------------------
# Container / nesting
# ---------------------------------------------------------------------------

class TestContainerLayout:
    def test_children_inside_parent(self):
        src = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      agent [type: t, label: "Agent"]
      charm [type: t, label: "Charm"]
    }
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: pod }
}
"""
        layout = solve_src(src)
        pod = layout.find("pod")
        agent = layout.find("agent")
        charm = layout.find("charm")
        assert agent is not None
        assert charm is not None
        # Children must be inside the parent.
        for child in (agent, charm):
            assert child.rect.x >= pod.rect.x
            assert child.rect.y >= pod.rect.y
            assert child.rect.x2 <= pod.rect.x2 + 0.5
            assert child.rect.y2 <= pod.rect.y2 + 0.5

    def test_collapsed_node_has_no_children_in_layout(self):
        src = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      agent [type: t, label: "Agent"]
    }
    b [type: t, label: "B"]
  }
  edges {}
}
diagram "D" from "M" {
  select {
    nodes: pod b
    collapse: pod
  }
}
"""
        layout = solve_src(src)
        pod = layout.find("pod")
        assert pod is not None
        # Children not rendered when collapsed.
        assert layout.find("agent") is None

    def test_parent_size_grows_to_fit_children(self):
        src = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      a [type: t, label: "A long label that makes the child wide"]
    }
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: pod }
}
"""
        layout = solve_src(src)
        pod = layout.find("pod")
        child = layout.find("a")
        # Parent must be at least as wide as child plus padding.
        assert pod.rect.w >= child.rect.w


# ---------------------------------------------------------------------------
# Min-width constraint
# ---------------------------------------------------------------------------

class TestMinWidth:
    def test_min_width_respected(self):
        src = SIMPLE_MODEL + """\
diagram "D" from "M" {
  select { nodes: a b }
  positions {
    a min-width: 200
    a left-of b gap: 20
  }
}
"""
        layout = solve_src(src)
        a = layout.find("a")
        assert a.rect.w >= 200 - 0.1


# ---------------------------------------------------------------------------
# Juju example
# ---------------------------------------------------------------------------

class TestJujuLayout:
    def test_k8s_topology_solves(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
        f = parse(src)
        validate(f)
        diagram = next(d for d in f.diagrams if d.name == "K8s deployment topology")
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        assert layout.bounds.w > 0
        assert layout.bounds.h > 0
        # All selected top-level nodes present.
        for nid in ("controller_pod", "unit_pod", "k8s", "charmhub"):
            assert layout.find(nid) is not None

    def test_unit_focus_collapsed_controller(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
        f = parse(src)
        validate(f)
        diagram = next(d for d in f.diagrams if d.name == "Unit focus")
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        # controller_pod collapsed — its children must not appear.
        assert layout.find("controller_pod") is not None
        assert layout.find("jujud") is None
        # unit_pod expanded — children present.
        assert layout.find("unit_agent") is not None
        assert layout.find("charm") is not None

    def test_k8s_topology_positions_respected(self):
        """k8s is above controller_pod in the K8s topology view."""
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
        f = parse(src)
        validate(f)
        diagram = next(d for d in f.diagrams if d.name == "K8s deployment topology")
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        k8s = layout.find("k8s")
        ctrl = layout.find("controller_pod")
        # k8s above controller_pod means k8s.y2 <= controller_pod.y
        assert k8s.rect.y2 <= ctrl.rect.y + 0.5
