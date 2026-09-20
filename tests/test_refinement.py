"""ADR-007 acceptance — the refinement view.

The goal-state sentence, pinned as the definition of done: an
auto-layout view that declares the two-plane arrangement
("user-client-controller-apps in one plane; clouds and charmhub in an
orthogonal plane, above and below the controller") renders through the
floor pipeline with the planes honored, the routing vocabulary
respected, port discipline where bend-neutral, and byte-stable
geometry. This is the "Intro: Juju enters" graph with declared
constraints instead of a hand-solved positions block.
"""
import os

import pytest

from ggarch import parse, validate, solve, route, render

os.environ.pop("GGARCH_LAYOUT", None)

SRC = """\
model "M" {
  nodes {
    user      [type: person,        label: "User"]
    client    [type: juju-software, label: "Client"]
    controller[type: juju-software, label: "Controller"]
    cloud_a   [type: external,      label: "cloud 1"]
    cloud_b   [type: external,      label: "cloud 2"]
    charmhub  [type: external,      label: "Charmhub"]
    app1      [type: charm,         label: "app 1"]
    app2      [type: charm,         label: "app 2"]
    app3      [type: charm,         label: "app 3"]
  }
  edges {
    user -> client       [type: control, label: "sends commands to"]
    client -> controller [type: api,     label: "calls Juju API on"]
    controller -> cloud_a  [type: control, label: "provisions on"]
    controller -> cloud_b  [type: control, label: "provisions on"]
    controller -> charmhub [type: api,     label: "fetches charms"]
    app1 -> controller   [type: control, label: "converges toward"]
    app2 -> controller   [type: control, label: "converges toward"]
    app3 -> controller   [type: control, label: "converges toward"]
  }
}
diagram "Juju enters (refined)" from "M" {
  select { nodes: user client controller cloud_a cloud_b charmhub
           app1 app2 app3
           edges: type control type api }
  positions {
    // The horizontal plane: the spine on one y.
    user   left-of client
    user   align-middle client
    client left-of controller
    client align-middle controller
    // The vertical plane: clouds fanned above (arrows out of the
    // controller's mid-north), charmhub below on the same axis.
    fan [cloud_a cloud_b] above controller gap: 40 spacing: 120
    charmhub below controller gap: 40
    charmhub align-centre controller
    // The app fan right of controller: gap sized for the labels —
    // three "converges toward" strokes into the mid-east face need
    // the run for their labels to separate.
    fan [app1 app2 app3] right-of controller gap: 140
  }
  emphasize {
    // The argument: Juju machinery between the user and the
    // applications. The path is adjacency-checked; the fan members
    // are declared as nodes (they are parallel, not sequential — the
    // validator rejects a chain through them). Edges are induced:
    // loud when both endpoints are loud.
    path [user client controller app1]
    nodes [app2 app3]
  }
}
"""


@pytest.fixture(scope="module")
def refined():
    f = parse(SRC)
    validate(f)
    d = f.diagrams[0]
    m = f.get_model(d.model_name)
    return d, m, route(solve(d, m), m, d.select)


class TestJujuEntersRefined:
    def test_horizontal_plane_spine(self, refined):
        """user, client, controller share one y (align-middle chain)."""
        d, m, rl = refined
        ys = [rl.layout.find(nid).rect.y for nid in
              ("user", "client", "controller")]
        assert max(ys) - min(ys) <= 0.5, f"spine not y-aligned: {ys}"

    def test_vertical_plane(self, refined):
        """clouds fanned above the controller (one row, centred on its
        axis, arrows from the mid-north face), charmhub below on the
        same axis."""
        d, m, rl = refined
        cy = rl.layout.find("controller").rect
        ca = rl.layout.find("cloud_a").rect
        cb = rl.layout.find("cloud_b").rect
        ch = rl.layout.find("charmhub").rect
        # fan row: same y, centred on the controller's x
        assert abs(ca.y - cb.y) <= 0.5, f"fan row broken: {ca.y}, {cb.y}"
        centre = (ca.cx + cb.cx) / 2
        assert abs(centre - cy.cx) <= 0.5, \
            f"fan not centred on the controller: {centre} vs {cy.cx}"
        assert ca.y2 <= cy.y and cb.y2 <= cy.y
        assert abs(ch.cx - cy.cx) <= 0.5, \
            f"charmhub off the axis: {ch.cx} vs {cy.cx}"
        assert cy.y2 <= ch.y
        # both cloud edges leave the controller's mid-north face and
        # enter the clouds' south faces
        rects = {n.id: n.rect for n in rl.layout.nodes}
        for e in rl.edges:
            if e.source_id != "controller" \
                    or not e.target_id.startswith("cloud"):
                continue
            ex, en = e.points[0], e.points[-1]
            sr, tr = rects["controller"], rects[e.target_id]
            assert abs(ex.x - sr.cx) <= 24, \
                f"{e.target_id} edge not from mid-north: {ex.x} vs {sr.cx}"
            assert abs(ex.y - sr.y) < 1, f"exit not on north face: {ex}"
            assert abs(en.y - (tr.y + tr.h)) < 1, \
                f"entry not on south face: {en}"

    def test_app_fan_right_of_controller(self, refined):
        """The app fan is a column right of the controller, members
        stacked and centred on the spine."""
        d, m, rl = refined
        cy = rl.layout.find("controller").rect
        apps = [rl.layout.find(f"app{i}").rect for i in (1, 2, 3)]
        for r in apps:
            assert r.x >= cy.x2, f"app left of controller: {r.x}"
        xs = [r.x for r in apps]
        assert max(xs) - min(xs) <= 0.5, f"fan column not aligned: {xs}"
        centre = (min(r.y for r in apps) + max(r.y2 for r in apps)) / 2
        assert abs(centre - (cy.y + cy.h / 2)) <= 40, \
            f"fan not centred on the spine: {centre}"

    def test_route_vocabulary(self, refined):
        """The ADR-003 law holds on the refined view: <= 2 bends, no
        edge crosses a node rect."""
        from ggarch.geometry import seg_enters_rect
        d, m, rl = refined
        rects = {n.id: n.rect for n in rl.layout.nodes}
        for e in rl.edges:
            assert e.turns <= 2, \
                f"{e.source_id}->{e.target_id}: {e.turns} bends"
        for e in rl.edges:
            for nid, r in rects.items():
                if nid in (e.source_id, e.target_id):
                    continue
                pts = [(p.x, p.y) for p in e.points]
                for p, q in zip(pts, pts[1:]):
                    assert not seg_enters_rect(
                        p, q, (r.x, r.y, r.x2, r.y2)), \
                        f"{e.source_id}->{e.target_id} crosses {nid}"

    def test_port_discipline_bend_neutral(self, refined):
        """Inter-column edges bind the axis-facing pair where
        bend-neutral (ADR-007: discipline as preference). The spine
        binds fully; the app fan's third edge keeps a dodge — three
        labelled edges into one shared face overprint their labels on
        the disciplined straight, and label costs outrank the
        preference (the accepted trade, documented in the router)."""
        d, m, rl = refined
        rects = {n.id: n.rect for n in rl.layout.nodes}
        checked = bound = 0
        undisciplined: list[str] = []
        for e in rl.edges:
            sr, tr = rects[e.source_id], rects[e.target_id]
            ex, en = e.points[0], e.points[-1]
            if tr.x > sr.x + sr.w - 1:
                # left -> right: exit EAST, enter WEST
                ok = (abs(ex.x - (sr.x + sr.w)) < 1
                      and abs(en.x - tr.x) < 1)
            elif sr.x > tr.x + tr.w - 1:
                # right -> left: exit WEST, enter EAST
                ok = (abs(ex.x - sr.x) < 1
                      and abs(en.x - (tr.x + tr.w)) < 1)
            else:
                continue  # same column: NORTH/SOUTH vocabulary
            if e.source_id == "controller" \
                    and e.target_id.startswith("cloud"):
                continue  # vertical plane: the mid-north fan is
                          # asserted in test_vertical_plane
            if e.turns <= 1:
                checked += 1
                bound += ok
                if not ok:
                    undisciplined.append(f"{e.source_id}->{e.target_id}")
        assert checked >= 5, f"too few bend-neutral inter-column edges: {checked}"
        assert bound >= checked - 1, \
            f"{checked - bound} undisciplined: {undisciplined}"
        # The spine — the preattentive flow — is unconditional.
        for pair in (("user", "client"), ("client", "controller")):
            e = next(e for e in rl.edges
                     if (e.source_id, e.target_id) == pair)
            sr, tr = rects[pair[0]], rects[pair[1]]
            assert abs(e.points[0].x - (sr.x + sr.w)) < 1
            assert abs(e.points[-1].x - tr.x) < 1

    def test_fan_labels_separated(self, refined):
        """The three app labels neither overlap one another nor ride
        another edge's stroke — the reason the fan gap is sized."""
        d, m, rl = refined
        from ggarch.renderer import label_geometry
        strips = {}
        segs = {}
        for e in rl.edges:
            if not e.label:
                continue
            lg = label_geometry([(p.x, p.y) for p in e.points],
                                e.label, 0.5)
            if lg.strip is not None:
                strips[(e.source_id, e.target_id)] = lg.strip
            segs[(e.source_id, e.target_id)] = [
                ((p.x, p.y), (q.x, q.y)) for p, q in zip(e.points, e.points[1:])]
        from ggarch.geometry import rects_overlap, seg_box_dist
        app_keys = [k for k in strips if k[0].startswith("app")]
        assert len(app_keys) == 3, f"labels missing: {app_keys}"
        for i, k1 in enumerate(app_keys):
            for k2 in app_keys[i + 1:]:
                s1, s2 = strips[k1], strips[k2]
                assert not rects_overlap(s1, s2, eps=0.0), \
                    f"labels overlap: {k1} vs {k2}"
        for k, strip in strips.items():
            if not k[0].startswith("app"):
                continue
            half_w = 1.0 + 2.0  # ROUTE_STROKE_W/2 + clearance
            for other, other_segs in segs.items():
                if other == k:
                    continue
                for a, b in other_segs:
                    assert seg_box_dist(a, b, strip) >= half_w, \
                        f"{other} rides {k}'s label"

    def test_byte_stable(self):
        """Two solves, identical geometry — the refinement solve is
        deterministic."""
        f = parse(SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        k1 = [(n.id, n.rect.x, n.rect.y) for n in solve(d, m).nodes]
        k2 = [(n.id, n.rect.x, n.rect.y) for n in solve(d, m).nodes]
        assert k1 == k2

    def test_renders(self, refined):
        d, m, rl = refined
        svg = render(rl, m, d)
        assert "<svg" in svg

    def test_emphasis_renders_loud_and_dim(self, refined):
        """The salience stack: emphasized strokes at weight 3, the
        remainder in dim groups; nodes on the path stay loud."""
        d, m, rl = refined
        svg = render(rl, m, d)
        # emphasized stroke width present exactly on the path edges
        assert 'stroke-width="3.0"' in svg
        dim_groups = svg.count('opacity="0.35"')
        assert dim_groups > 0, "no dim groups rendered"
        # loud: user, client, controller, apps (6 nodes) + induced
        # loud edges (spine + three converging). dim: charmhub + two
        # clouds (3 nodes) + their three edges = 6 groups.
        assert dim_groups == 6, f"expected 6 dim groups, saw {dim_groups}"

    def test_emphasis_path_validated(self):
        """A path claiming adjacency the view does not draw is a lie
        the validator catches; an unknown node too."""
        bad = SRC.replace(
            "path [user client controller app1]\n    nodes [app2 app3]",
            "path [user controller client]\n    nodes [app2 app3]")
        with pytest.raises(Exception, match="no edge between"):
            validate(parse(bad))
        unknown = SRC.replace(
            "path [user client controller app1]\n    nodes [app2 app3]",
            "path [user client nonexistent]\n    nodes [app2 app3]")
        with pytest.raises(Exception, match="not selected"):
            validate(parse(unknown))
        parallel = SRC.replace(
            "path [user client controller app1]\n    nodes [app2 app3]",
            "path [user client controller app1 app2]\n    nodes [app3]")
        with pytest.raises(Exception, match="no edge between"):
            validate(parse(parallel))
