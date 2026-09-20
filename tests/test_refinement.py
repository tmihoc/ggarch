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
    // The vertical plane: clouds stacked above, charmhub below,
    // all on the controller's x.
    cloud_b  above controller gap: 40
    cloud_a  above cloud_b  gap: 40
    cloud_a  align-centre controller
    cloud_b  align-centre controller
    charmhub below controller gap: 40
    charmhub align-centre controller
    // The app fan right of controller, centred on the spine.
    fan [app1 app2 app3] right-of controller gap: 60
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

    def test_vertical_plane_column(self, refined):
        """clouds and charmhub share the controller's centre x (the
        align-centre axis), clouds above, charmhub below."""
        d, m, rl = refined
        cxs = [rl.layout.find(nid).rect.cx for nid in
               ("cloud_a", "cloud_b", "controller", "charmhub")]
        assert max(cxs) - min(cxs) <= 0.5, f"plane not centre-aligned: {cxs}"
        cy = rl.layout.find("controller").rect
        ca = rl.layout.find("cloud_a").rect
        cb = rl.layout.find("cloud_b").rect
        ch = rl.layout.find("charmhub").rect
        assert ca.y2 <= cb.y <= cy.y
        assert cy.y2 <= ch.y

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

    def test_byte_stable(self, d_and_m=None):
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
