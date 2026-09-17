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
        src = (Path(__file__).parent.parent / "examples" / "topology.ggarch").read_text()
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
        src = (Path(__file__).parent.parent / "examples" / "topology.ggarch").read_text()
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
        src = (Path(__file__).parent.parent / "examples" / "topology.ggarch").read_text()
        f = parse(src)
        validate(f)
        diagram = next(d for d in f.diagrams if d.name == "K8s deployment topology")
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        k8s = layout.find("k8s")
        ctrl = layout.find("controller_pod")
        # k8s above controller_pod means k8s.y2 <= controller_pod.y
        assert k8s.rect.y2 <= ctrl.rect.y + 0.5


# ---------------------------------------------------------------------------
# Fan constraint
# ---------------------------------------------------------------------------

FAN_MODEL = """\
model "M" {
  nodes {
    anchor [type: t, label: "Anchor"]
    a      [type: t, label: "A"]
    b      [type: t, label: "B"]
    c      [type: t, label: "C"]
  }
  edges {}
}
"""

class TestFanConstraint:
    def test_fan_above_places_members_above_anchor(self):
        src = FAN_MODEL + """\
diagram "D" from "M" {
  select { nodes: anchor a b c }
  positions { fan [a b c] above anchor gap: 40 }
}
"""
        layout = solve_src(src)
        anchor = layout.find("anchor")
        for nid in ("a", "b", "c"):
            n = layout.find(nid)
            assert n.rect.y2 + 40 <= anchor.rect.y + 0.5, \
                f"{nid} not above anchor (y2={n.rect.y2:.1f}, anchor.y={anchor.rect.y:.1f})"

    def test_fan_above_members_same_row(self):
        src = FAN_MODEL + """\
diagram "D" from "M" {
  select { nodes: anchor a b c }
  positions { fan [a b c] above anchor gap: 40 }
}
"""
        layout = solve_src(src)
        cys = [layout.find(nid).rect.cy for nid in ("a", "b", "c")]
        assert max(cys) - min(cys) < 0.5, "fan members not on same horizontal row"

    def test_fan_above_members_spaced_left_to_right(self):
        src = FAN_MODEL + """\
diagram "D" from "M" {
  select { nodes: anchor a b c }
  positions { fan [a b c] above anchor gap: 40 spacing: 20 }
}
"""
        layout = solve_src(src)
        xa = layout.find("a").rect.x2
        xb = layout.find("b").rect.x
        xc_l = layout.find("c").rect.x
        xb_r = layout.find("b").rect.x2
        assert xb >= xa + 20 - 0.5, "a and b not spaced"
        assert xc_l >= xb_r + 20 - 0.5, "b and c not spaced"

    def test_fan_above_centred_on_anchor(self):
        """Middle member of a 3-node fan should be centred on the anchor's cx."""
        src = FAN_MODEL + """\
diagram "D" from "M" {
  select { nodes: anchor a b c }
  positions { fan [a b c] above anchor gap: 40 }
}
"""
        layout = solve_src(src)
        mid_cx  = layout.find("b").rect.cx
        anch_cx = layout.find("anchor").rect.cx
        assert abs(mid_cx - anch_cx) < 1.0, \
            f"middle member cx={mid_cx:.1f} not aligned to anchor cx={anch_cx:.1f}"

    def test_fan_right_of_places_members_right_of_anchor(self):
        src = FAN_MODEL + """\
diagram "D" from "M" {
  select { nodes: anchor a b c }
  positions { fan [a b c] right-of anchor gap: 40 }
}
"""
        layout = solve_src(src)
        anchor = layout.find("anchor")
        for nid in ("a", "b", "c"):
            n = layout.find(nid)
            assert n.rect.x >= anchor.rect.x2 + 40 - 0.5, \
                f"{nid} not right of anchor"

    def test_fan_right_of_centred_on_anchor(self):
        """Middle member of a 3-node right-of fan centred on anchor's cy."""
        src = FAN_MODEL + """\
diagram "D" from "M" {
  select { nodes: anchor a b c }
  positions { fan [a b c] right-of anchor gap: 40 }
}
"""
        layout = solve_src(src)
        mid_cy  = layout.find("b").rect.cy
        anch_cy = layout.find("anchor").rect.cy
        assert abs(mid_cy - anch_cy) < 1.0, \
            f"middle member cy={mid_cy:.1f} not aligned to anchor cy={anch_cy:.1f}"

    def test_fan_two_members_above(self):
        """Even-N fan: both members above anchor, group midpoint centred on anchor."""
        src = FAN_MODEL + """\
diagram "D" from "M" {
  select { nodes: anchor a b }
  positions { fan [a b] above anchor gap: 40 }
}
"""
        layout = solve_src(src)
        anchor = layout.find("anchor")
        for nid in ("a", "b"):
            n = layout.find(nid)
            assert n.rect.y2 + 40 <= anchor.rect.y + 0.5
        # Even N: group midpoint (average cx of all members) == anchor cx.
        midpoint_cx = (layout.find("a").rect.cx + layout.find("b").rect.cx) / 2
        assert abs(midpoint_cx - anchor.rect.cx) < 1.0, \
            f"group midpoint cx={midpoint_cx:.1f} != anchor cx={anchor.rect.cx:.1f}"

    def test_fan_parses_in_ggarch_source(self):
        """fan constraint round-trips through parse → validate → solve."""
        from ggarch import validate
        src = FAN_MODEL + """\
diagram "D" from "M" {
  select { nodes: anchor a b c }
  positions { fan [a b c] above anchor gap: 40 spacing: 20 }
}
"""
        from ggarch import parse
        f = parse(src)
        validate(f)
        d = f.diagrams[0]
        assert any(hasattr(c, "members") for c in d.constraints)


class TestLeafWidthPin:
    """Regression (0.24.1): anchored first node + align-centre must not
    balloon the node's width.

    The origin anchor pins the first selected node's x at 0 (weak). If that
    node is also align-centre'd to a partner, the conflict was silently
    absorbed by the free width variable — the node rendered at twice its
    centre offset (e.g. 321.6px for a 147.2px label). Leaf width is now
    pinned at natural size with STRONG priority, mirroring the existing
    height pin.
    """

    def test_anchored_first_node_keeps_natural_width(self):
        src = """\
model "M" {
  nodes {
    top [type: juju-software, label: "Short"]
    wide [type: juju-software, label: "A considerably wider label"]
  }
  edges { top -> wide [type: control, label: "depends on"] }
}
diagram "D" from "M" {
  select { nodes: top wide }
  positions {
    top above wide gap: 60
    top align-centre wide
  }
}
"""
        f = parse(src)
        validate(f)
        layout = solve(f.diagrams[0], f.get_model("M"))
        top = layout.find("top")
        assert top is not None
        # Natural width for a 5-char label is far below the ballooned
        # 2x-centre value; assert it stays under a generous bound.
        assert top.rect.w < 120, (
            f"anchored node ballooned: w={top.rect.w:.1f}"
        )
