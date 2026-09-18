"""Router tests — obstacle-aware shortest paths over strips (ADR-003).

Routes are found by search: A* over a Hanan grid with 8-neighbour
moves, cost = length + fixed turn penalty. The search chooses exit and
entry faces; field-qualified anchors stay pinned. Obstacles: node
rects (ancestor-or-self of either endpoint exempt), and earlier edges'
strips (offsets emerge). When no clear path exists the router returns
the cheapest-collision path and reports it.
"""
from ggarch import parse, validate
from ggarch.solver import solve
from ggarch.router import Point, Rect, route, route_between
from ggarch.geometry import seg_enters_rect, seg_seg_dist


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

THREE_IN_A_ROW = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
    c [type: t, label: "C"]
  }
  edges {
    a -> c [type: api, label: "across"]
  }
}
diagram "D" from "M" {
  select { nodes: a b c }
  positions {
    a left-of b gap: 40
    b left-of c gap: 40
    a align-middle b
    b align-middle c
  }
}
"""


def path_enters_rect(points, rect, eps=0.5):
    """Does the polyline pass through the rect's interior (audit
    semantics)?"""
    box = (rect.x + eps, rect.y + eps, rect.x2 - eps, rect.y2 - eps)
    pts = [(p.x, p.y) for p in points]
    return any(seg_enters_rect(pts[i], pts[i + 1], box)
               for i in range(len(pts) - 1))


# ---------------------------------------------------------------------------
# Obstacle-aware search
# ---------------------------------------------------------------------------

class TestObstacleAware:
    def test_straight_when_clear(self):
        """No obstacle between the endpoints -> straight 2-point path."""
        rl, _, _ = solve_and_route(SIMPLE_TWO)
        e = rl.edges[0]
        assert len(e.points) == 2
        assert e.turns == 0
        assert e.residuals == []

    def test_edge_bends_around_blocking_node(self):
        """A node between the endpoints is an obstacle: the routed path
        must clear its interior (the old router went straight through)."""
        rl, _, _ = solve_and_route(THREE_IN_A_ROW)
        e = rl.edges[0]
        b = rl.layout.find("b").rect
        assert not path_enters_rect(e.points, b)

    def test_bend_clears_by_the_corridor(self):
        """The bend clears the obstacle by the corridor half-width, not
        just by a hair: every path segment stays outside the rect."""
        rl, _, _ = solve_and_route(THREE_IN_A_ROW)
        e = rl.edges[0]
        b = rl.layout.find("b").rect
        margin = (b.x - 1, b.y - 1, b.x2 + 1, b.y2 + 1)
        pts = [(p.x, p.y) for p in e.points]
        assert not any(seg_enters_rect(pts[i], pts[i + 1], margin)
                       for i in range(len(pts) - 1))

    def test_turns_only_at_obstacles(self):
        """With the turn penalty high, a path bends only to clear the
        obstacle: a handful of bends, not a staircase."""
        rl, _, _ = solve_and_route(THREE_IN_A_ROW)
        e = rl.edges[0]
        assert 0 < e.turns <= 4

    def test_obstacle_below_the_line_is_cleared_too(self):
        """Obstacle BELOW the direct line: same clearing behaviour."""
        src = THREE_IN_A_ROW.replace(
            "    a align-middle b\n",
            "    b below a gap: 30\n")
        rl, _, _ = solve_and_route(src)
        e = rl.edges[0]
        b = rl.layout.find("b").rect
        assert not path_enters_rect(e.points, b)


class TestFaces:
    def test_edge_starts_on_source_border(self):
        rl, _, _ = solve_and_route(SIMPLE_TWO)
        e = rl.edges[0]
        r = rl.layout.find("a").rect
        on_border = (
            abs(e.start.x - r.x) < 0.1 or abs(e.start.x - r.x2) < 0.1
            or abs(e.start.y - r.y) < 0.1 or abs(e.start.y - r.y2) < 0.1)
        assert on_border

    def test_edge_ends_on_target_border(self):
        rl, _, _ = solve_and_route(SIMPLE_TWO)
        e = rl.edges[0]
        r = rl.layout.find("b").rect
        on_border = (
            abs(e.end.x - r.x) < 0.1 or abs(e.end.x - r.x2) < 0.1
            or abs(e.end.y - r.y) < 0.1 or abs(e.end.y - r.y2) < 0.1)
        assert on_border

    def test_same_level_stays_flat_and_centred(self):
        """Same-level left-of nodes: face centres, flat, straight — the
        default look is unchanged when nothing blocks."""
        rl, _, _ = solve_and_route(SIMPLE_TWO)
        e = rl.edges[0]
        src_node = rl.layout.find("a")
        assert abs(e.start.x - src_node.rect.x2) < 0.1
        assert abs(e.start.y - src_node.rect.cy) < 0.1

    def test_field_qualified_anchor_stays_pinned(self):
        """Field-qualified endpoints keep their pinned facing-face anchors
        at the fields' mid-y (author speech outranks heuristics)."""
        src = """\
model "M" {
  nodes {
    r1 [type: record, label: "R1"] {
      fields {
        f1 [label: "f1"]
        f2 [label: "f2"]
      }
    }
    r2 [type: record, label: "R2"] {
      fields {
        g1 [label: "g1"]
        g2 [label: "g2"]
      }
    }
  }
  edges { r1.f1 -> r2.g2 [type: data, label: "fk"] }
}
diagram "D" from "M" {
  select { nodes: r1 r2 }
  positions { r1 left-of r2 gap: 40 }
}
"""
        rl, _, _ = solve_and_route(src)
        assert len(rl.edges) == 1
        e = rl.edges[0]
        # Pinned: start on r1's right face at f1's row, flat at mid-y.
        assert abs(e.start.x - rl.layout.find("r1").rect.x2) < 0.1
        assert abs(e.start.y - e.end.y) < 0.1


class TestPairsAndStrips:
    def test_anti_parallel_pair_separates(self):
        """Two anti-parallel edges between the same pair route at
        distinct offsets: their corridors do not overlap (the 1/3-2/3
        label anchor workaround is redundant)."""
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "one"]
    b -> a [type: api, label: "two"]
  }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 60 }
}
"""
        rl, _, _ = solve_and_route(src)
        assert len(rl.edges) == 2
        e1, e2 = rl.edges
        assert e1.strip is not None and e2.strip is not None
        d = seg_seg_dist(
            (e1.points[0].x, e1.points[0].y),
            (e1.points[-1].x, e1.points[-1].y),
            (e2.points[0].x, e2.points[0].y),
            (e2.points[-1].x, e2.points[-1].y))
        assert d >= e1.strip.half_w + e2.strip.half_w

    def test_shared_face_fan_gets_offsets(self):
        """A fan from one node face: sibling corridors do not overlap
        beyond the shared face."""
        src = """\
model "M" {
  nodes {
    hub [type: t, label: "Hub"]
    x [type: t, label: "X"]
    y [type: t, label: "Y"]
  }
  edges {
    hub -> x [type: api, label: "one"]
    hub -> y [type: api, label: "two"]
  }
}
diagram "D" from "M" {
  select { nodes: hub x y }
  positions {
    hub left-of x gap: 60
    hub left-of y gap: 60
    x above y gap: 20
    x align-centre y
  }
}
"""
        rl, _, _ = solve_and_route(src)
        e1, e2 = rl.edges
        assert e1.strip is not None and e2.strip is not None
        # The two strokes leave the hub's right face at distinct
        # offsets; their corridors do not overlap mid-span.
        d = seg_seg_dist(
            (e1.points[0].x, e1.points[0].y),
            (e1.points[-1].x, e1.points[-1].y),
            (e2.points[0].x, e2.points[0].y),
            (e2.points[-1].x, e2.points[-1].y))
        assert d >= e1.strip.half_w + e2.strip.half_w


class TestResiduals:
    def test_detour_around_wall_is_clear(self):
        """A wall between the endpoints: the router detours around it
        honestly (no box explosion, no crossing) and reports no
        residuals — a clear path always wins over a cheaper crossing."""
        src_rect = Rect(0, 0, 40, 20)
        tgt_rect = Rect(200, 0, 40, 20)
        wall_box = (100.0, -400.0, 140.0, 400.0)   # 800px tall wall
        pts = route_between(src_rect, tgt_rect, [(wall_box, "wall")])
        assert len(pts) >= 2
        pts_t = [(p.x, p.y) for p in pts]
        assert not any(seg_enters_rect(pts_t[i], pts_t[i + 1], wall_box)
                       for i in range(len(pts_t) - 1))

    def test_clear_route_has_no_residuals(self):
        rl, _, _ = solve_and_route(SIMPLE_TWO)
        assert rl.edges[0].residuals == []


class TestAncestorExemption:
    def test_container_interior_is_passable(self):
        """An edge between siblings inside a container may cross the
        container's interior: the container is an ancestor, not an
        obstacle."""
        src = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      a [type: t, label: "A"]
      b [type: t, label: "B"]
    }
  }
  edges { a -> b [type: api, label: "in-pod"] }
}
diagram "D" from "M" {
  select { nodes: pod }
  positions { pod direction: right }
}
"""
        rl, _, _ = solve_and_route(src)
        e = rl.edges[0]
        # The straight sibling route crosses the pod interior legally
        # (the container is an ancestor of both endpoints).
        assert e.residuals == []


# ---------------------------------------------------------------------------
# Legacy compatibility
# ---------------------------------------------------------------------------

class TestLegacy:
    def test_edge_label_and_type_preserved(self):
        rl, _, _ = solve_and_route(SIMPLE_TWO)
        e = rl.edges[0]
        assert e.label == "calls"
        assert e.edge_type == "api"

    def test_missing_endpoint_skipped(self):
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
        assert len(rl.edges) == 1
        assert rl.edges[0].target_id == "b"

    def test_stream_edge_dashed_and_ipc_dotted(self):
        for edge_type, style in (("stream", "dashed"), ("ipc", "dotted")):
            src = SIMPLE_TWO.replace("type: api", f"type: {edge_type}")
            rl, _, _ = solve_and_route(src)
            assert rl.edges[0].style == style

    def test_k8s_topology_routes(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples"
               / "topology.ggarch").read_text()
        f = parse(src)
        validate(f)
        diagram = next(d for d in f.diagrams
                       if d.name == "K8s deployment topology")
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        rl = route(layout, model, diagram.select)
        assert len(rl.edges) > 0
        for e in rl.edges:
            assert len(e.points) >= 2
            assert e.strip is not None
