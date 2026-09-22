"""Regression tests for the symmetric-port rule (2026-09-21).

The where-on-the-face layer: every DRAWN multi-anchor face distributes
symmetrically about the face midpoint. The router enforces it with
per-face symmetric port sets; the corner landing (the border-ride
law's remedy) is not an admissible anchor for a set face, and a
straight may never ride an endpoint border.

Measured defects this pins:
- user_rec's bottom face had TWO same-sign arrows sharing the exact
  bottom-right corner (183.2, 183.2) — the ladder beat the fan slots
  on length, and the corner-safe closure missed because the recorded
  face ('right') differed from the enumerated face ('bottom').
- The CMR synthesized straight ran along BOTH endpoints' top borders
  (a double ride) once the port sets made it the cheapest clear
  route — the free-path vocabulary loop never ride-checked straights.
"""
import os

import pytest

from ggarch import parse, validate
from ggarch.solver import solve
from ggarch.router import route

CORPUS = os.path.join(os.path.expanduser("~"), "git", "juju", "docs")

requires_corpus = pytest.mark.skipif(
    not os.path.exists(os.path.join(CORPUS, "juju.ggarch")),
    reason="juju docs corpus not present")


def _load():
    with open(os.path.join(CORPUS, "juju.ggarch")) as fh:
        f = parse(fh.read())
    validate(f)
    return f


@pytest.fixture(scope="module")
def full_spine():
    f = _load()
    d = next(x for x in f.diagrams
             if x.name == "Data model (full spine)")
    m = f.get_model(d.model_name)
    return route(solve(d, m), m, d.select)


@pytest.fixture(scope="module")
def cmr_synth():
    f = _load()
    d = next(x for x in f.diagrams
             if x.name == "Cross-model relation (CMR) (synthesized)")
    m = f.get_model(d.model_name)
    return route(solve(d, m), m, d.select)


def _edge(rl, source, target):
    hits = [e for e in rl.edges
            if e.source_id == source and e.target_id == target]
    assert hits, f"edge {source}->{target} not routed"
    return hits[0]


def _rides_an_endpoint_border(pts, rects):
    """Does the first or last leg collide-with-and-overlap an endpoint
    border (the audit's border-ride check)? Mirrors _leg_rides."""
    for p_end, p_in, rect in ((pts[0], pts[1], rects[0]),
                              (pts[-1], pts[-2], rects[1])):
        if abs(p_end.x - p_in.x) < 0.5:      # vertical leg
            if (abs(p_end.x - rect.x) < 0.5
                    or abs(p_end.x - rect.x2) < 0.5):
                ylo, yhi = sorted((p_end.y, p_in.y))
                if min(yhi, rect.y2) - max(ylo, rect.y) > 0.5:
                    return True
        elif abs(p_end.y - p_in.y) < 0.5:    # horizontal leg
            if (abs(p_end.y - rect.y) < 0.5
                    or abs(p_end.y - rect.y2) < 0.5):
                xlo, xhi = sorted((p_end.x, p_in.x))
                if min(xhi, rect.x2) - max(xlo, rect.x) > 0.5:
                    return True
    return False


@requires_corpus
class TestSymmetricPorts:
    def test_fan_no_corner_stack(self, full_spine):
        """The user_rec out-fan must not share one corner anchor —
        the measured defect (183.2, 183.2) x2. The two arrows exit at
        distinct anchors; the owns edge sits ON user_rec's right-face
        port set {28, 52}."""
        rl = full_spine
        access = _edge(rl, "user_rec", "cloud_rec")
        owns = _edge(rl, "user_rec", "credential_rec")
        pa, pb = access.points[0], owns.points[0]
        assert (abs(pa.x - pb.x) > 0.5 or abs(pa.y - pb.y) > 0.5), \
            f"fan arrows share anchor ({pa.x}, {pa.y})"
        sets = getattr(rl.layout, "port_sets", {}) or {}
        right_set = sets.get("user_rec", {}).get("right")
        assert right_set, "user_rec right face has no port set"
        assert any(abs(pb.y - v) <= 1.0 for v in right_set), \
            f"owns anchor {pb.y} off user_rec right set {right_set}"

    def test_cmr_straight_does_not_ride(self, cmr_synth):
        """The CMR synthesized straight must not run along both
        endpoints' top borders (the double ride the port sets
        exposed): the straight-ride is rejected by the vocabulary."""
        rl = cmr_synth
        e = _edge(rl, "endpoint_rec", "application_rec")
        rects = (rl.layout.find("endpoint_rec").rect,
                 rl.layout.find("application_rec").rect)
        assert not _rides_an_endpoint_border(e.points, rects), \
            f"{e.source_id}->{e.target_id} rides a border: {e.points}"

    def test_port_sets_present_and_symmetric(self, full_spine):
        """The port sets the router built are symmetric about each
        face midpoint (a non-symmetric set would be a bug in the
        set builder, not the router)."""
        rl = full_spine
        sets = getattr(rl.layout, "port_sets", {}) or {}
        assert sets, "no port sets computed"
        for nid, faces in sets.items():
            r = rl.layout.find(nid)
            assert r is not None, f"port set for missing node {nid}"
            for face, coords in faces.items():
                on_width = face in ("top", "bottom")
                lo, hi = ((r.rect.x, r.rect.x + r.rect.w) if on_width
                          else (r.rect.y, r.rect.y + r.rect.h))
                mid = (lo + hi) / 2.0
                for c in coords:
                    assert any(abs(mid * 2 - c - m2) <= 1.0
                               for m2 in coords), \
                        f"{nid} {face} set {coords} not symmetric " \
                        f"about mid {mid} ({c} has no mirror)"