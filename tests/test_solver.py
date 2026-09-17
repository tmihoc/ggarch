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


AUTO_SRC = """\
model "M" {{
  nodes {{
    user [type: person, label: "User"]
    client [type: juju-software, label: "Client"]
    controller [type: juju-software, label: "Controller"]
    unit_a [type: juju-software, label: "Unit A"]
    unit_b [type: juju-software, label: "Unit B"]
  }}
  edges {{
    user -> client [type: control]
    client -> controller [type: api]
    controller -> unit_a [type: stream]
    controller -> unit_b [type: stream]
  }}
}}
diagram "{name}" from "M" {{
  select {{ nodes: user client controller unit_a unit_b }}
}}
"""


class TestViewAutoLayout:
    """Auto-layout as the default (0.25.0; SPEC "Position is content").

    When a view declares no positions at all, the solver synthesizes a
    layered layout: columns follow topological depth along the visible
    edges (main flow left-to-right), same-column nodes stack vertically.
    Before, unpositioned nodes collapsed onto each other -- the only
    spacing force was the label-gap machinery, which fires for labelled
    edges only, so unlabelled-edge views rendered all nodes at (0, 0).
    Views that declare positions are untouched: auto-layout is the
    floor, not the ceiling.
    """

    def _layout(self):
        f = parse(AUTO_SRC.format(name="auto"))
        validate(f)
        d = f.diagrams[0]
        return solve(d, f.get_model("M"))

    def test_chain_flows_left_to_right(self):
        lay = self._layout()
        xs = {n.id: n.rect.x for n in lay.nodes}
        assert xs["user"] < xs["client"] < xs["controller"] < xs["unit_a"]

    def test_branch_targets_stack_in_their_column(self):
        lay = self._layout()
        ua = lay.find("unit_a").rect
        ub = lay.find("unit_b").rect
        # Same column: centred on each other, vertically separated.
        assert abs(ua.cx - ub.cx) < 1.0
        assert ua.y != ub.y and abs(ua.cy - ub.cy) >= 60.0

    def test_no_overlaps(self):
        lay = self._layout()
        rects = [n.rect for n in lay.nodes]
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                assert (a.x + a.w <= b.x + 0.5 or b.x + b.w <= a.x + 0.5
                        or a.y + a.h <= b.y + 0.5 or b.y + b.h <= a.y + 0.5), \
                    f"overlap: {a} <-> {b}"

    def test_declared_positions_still_win(self):
        # A view WITH positions is laid out by the declared constraints;
        # auto-layout never runs (nothing must move).
        src = AUTO_SRC.format(name="manual").replace(
            'select { nodes: user client controller unit_a unit_b }',
            'select { nodes: user client }\n'
            '  positions { user above client gap: 50\n'
            '              user align-centre client }',
        )
        f = parse(src); validate(f)
        lay = solve(f.diagrams[0], f.get_model("M"))
        u = lay.find("user").rect
        c = lay.find("client").rect
        assert abs(u.cx - c.cx) < 1.0
        assert c.y - (u.y + u.h) >= 49.5

    def test_inter_container_edges_drive_container_placement(self):
        # A mesh between containers' children lays out the containers:
        # three controller instances with a Dqlite Raft mesh become
        # three columns, not one (ancestor mapping, 0.25.0).
        src = """\
model "M" {
  nodes {
    ctrl [type: container, label: "Controller node"] {
      agent [type: juju-software, label: "Controller agent"]
      dqlite [type: database, label: "Dqlite"]
    }
  }
  edges {
    dqlite -> dqlite [type: stream, label: "Raft sync", pairing: mesh]
  }
}
diagram "ha" from "M" {
  select {
    nodes: ctrl
    edges: type stream
    instances: ctrl [ { id: c1, label: "Controller 1" },
                      { id: c2, label: "Controller 2" },
                      { id: c3, label: "Controller 3" } ]
  }
}
"""
        f = parse(src); validate(f)
        lay = solve(f.diagrams[0], f.get_model("M"))
        xs = [lay.find(i).rect for i in ("c1", "c2", "c3")]
        assert xs[0].x < xs[1].x < xs[2].x, "instances must be separate columns"
        # Dqlite children separated far enough for the Raft-sync label.
        d1 = lay.find("c1/dqlite").rect
        d2 = lay.find("c2/dqlite").rect
        assert d2.x - (d1.x + d1.w) >= 80
