"""Corpus-backed regression tests for the 0.26.1 route vocabulary.

The 0.26.0 review measured a traceability regression on the REAL
corpus: monster detours (path/direct ratio up to 8.8x), multi-bend
weaves (up to 7 turns), spurious tail notches, near-corner grazing
entries. Toy geometry failed to reproduce this class, so these tests
run against the actual juju docs corpus views.

The route vocabulary they pin (the 0.26.1 decision):

- straight -> L (one bend) -> U (two bends, deliberate). No route
  exceeds two bends.
- Node rects are the only hard obstacles: no crossing, no graze.
  Earlier edges' strips are NOT obstacles — separation is deliberate
  anchor offsets (offsets are not bends), and any residual overlap is
  audited, never routed around.
- Annotation boxes/regions are meta elements, never obstacles.
"""
import math
import os
import subprocess
import sys

import pytest

from ggarch import parse, validate
from ggarch.solver import solve
from ggarch.router import route, ROUTE_STROKE_W
from ggarch.geometry import STRIP_PAD, seg_box_dist

CORPUS = os.path.join(os.path.expanduser("~"), "git", "juju", "docs")
CLEAR = ROUTE_STROKE_W / 2 + STRIP_PAD

requires_corpus = pytest.mark.skipif(
    not os.path.exists(os.path.join(CORPUS, "juju3.ggarch")),
    reason="juju docs corpus not present")

CORPUS_FILES = ("juju3.ggarch", "juju4.ggarch")


def _load(fname):
    with open(os.path.join(CORPUS, fname)) as fh:
        f = parse(fh.read())
    validate(f)
    return f


def _path_len(points):
    return sum(points[i].distance_to(points[i + 1])
               for i in range(len(points) - 1))


def _border_direct(sr, tr):
    """Border-to-border distance between two rects — the shortest
    arrow that could connect them (the user's yardstick: 1060/198)."""
    dx = max(tr.x - sr.x2, sr.x - tr.x2, 0.0)
    dy = max(tr.y - sr.y2, sr.y - tr.y2, 0.0)
    return math.hypot(dx, dy)


@pytest.fixture(scope="module")
def corpus():
    """{file: {view: RoutedLayout}} — solved and routed once."""
    out = {}
    for fname in CORPUS_FILES:
        f = _load(fname)
        views = {}
        for d in f.diagrams:
            m = f.get_model(d.model_name)
            views[d.name] = route(solve(d, m), m, d.select)
        out[fname] = views
    return out


def _find_edge(rl, source, target, label_substr=""):
    hits = [e for e in rl.edges
            if e.source_id == source and e.target_id == target
            and label_substr in (e.label or "")]
    assert hits, f"edge {source}->{target} [{label_substr}] not routed"
    return hits[0]


# ---------------------------------------------------------------------------
# The measured defect edges (user review, 2026-09-18)
# ---------------------------------------------------------------------------

@requires_corpus
class TestDefectEdges:
    def test_juju4_data_model_belongs_to_is_direct(self, corpus):
        """endpoint_rec -> application_rec measured 5.36x direct with 3
        turns (exits RIGHT, loops the canvas, enters the top face at a
        near-corner 45° anchor). The floor layers endpoint LEFT of
        application (longest-path: relation -> endpoint -> application),
        so the route is a short straight."""
        rl = corpus["juju4.ggarch"]["Data model"]
        e = _find_edge(rl, "endpoint_rec", "application_rec")
        sr = rl.layout.find("endpoint_rec").rect
        tr = rl.layout.find("application_rec").rect
        ratio = _path_len(e.points) / max(_border_direct(sr, tr), 1.0)
        assert e.turns <= 1
        assert ratio <= 1.2, f"ratio {ratio:.2f}, turns {e.turns}"

    def test_juju3_cross_model_has_two_per_side_is_direct(self, corpus):
        """relation_rec -> endpoint_rec measured 8.8x direct (525 px for
        a 60 px direct): the direct corridor was occupied by an earlier
        edge's strip and the old router detoured around the whole
        canvas. Strips are not obstacles: the route is the 60 px direct
        line (any overlap is audited, not routed around)."""
        rl = corpus["juju3.ggarch"]["Cross-model relation (CMR)"]
        e = _find_edge(rl, "relation_rec", "endpoint_rec")
        sr = rl.layout.find("relation_rec").rect
        tr = rl.layout.find("endpoint_rec").rect
        ratio = _path_len(e.points) / max(_border_direct(sr, tr), 1.0)
        assert e.turns == 0
        assert ratio <= 1.1, f"ratio {ratio:.2f}"

    def test_juju4_juju_enters_fan_has_no_weaves(self, corpus):
        """controller -> app1 / app2 measured 5 and 7 turns — weaves
        around earlier strips. Offsets, not bends: the fan routes
        straight from the controller's face."""
        rl = corpus["juju4.ggarch"]["Intro: Juju enters"]
        for tgt in ("app1", "app2"):
            e = _find_edge(rl, "controller", tgt)
            assert e.turns <= 1, f"controller->{tgt}: {e.turns} turns"

    def test_juju3_unpacked_fan_is_left_aligned(self, corpus):
        """The unit fanout right of the controller is a column sharing
        its LEFT edge (the edge facing the anchor). Centre-aligning the
        unequal members forced symmetric container inflation — u_app1/u_app3
        rendered 1359px wide with ~660px of empty container."""
        rl = corpus["juju3.ggarch"]["Intro: Juju unpacked"]
        xs = [rl.layout.find(f"u_app{i}_0").rect.x for i in (1, 2, 3)]
        assert max(xs) - min(xs) <= 0.5, f"fan column not aligned: {xs}"

    def test_juju3_juju_enters_app3_has_no_weave(self, corpus):
        """controller -> app3 measured 7 turns (juju3 twin)."""
        rl = corpus["juju3.ggarch"]["Intro: Juju enters"]
        e = _find_edge(rl, "controller", "app3")
        assert e.turns <= 1, f"{e.turns} turns"


# ---------------------------------------------------------------------------
# Vocabulary invariants over the whole corpus
# ---------------------------------------------------------------------------

@requires_corpus
class TestVocabulary:
    def test_no_route_exceeds_two_bends(self, corpus):
        """The vocabulary is straight / L / U — random multi-bend
        polylines are out (user position, 2026-09-18)."""
        for fname, views in corpus.items():
            for view, rl in views.items():
                for e in rl.edges:
                    assert e.turns <= 2, (
                        f"{fname} {view}: {e.source_id}->{e.target_id} "
                        f"has {e.turns} bends")

    def test_no_node_crossings(self, corpus):
        """Arrows over boxes must STAY at zero (the one 0.26.0 win the
        user kept)."""
        from ggarch.geometry import seg_enters_rect
        for fname, views in corpus.items():
            for view, rl in views.items():
                rects = {}
                def walk(n):
                    rects[n.id] = n.rect
                    for c in n.children:
                        walk(c)
                for n in rl.layout.nodes:
                    walk(n)
                for e in rl.edges:
                    anc = _ancestors(rl.layout, e.source_id) \
                        | _ancestors(rl.layout, e.target_id) \
                        | {e.source_id, e.target_id}
                    pts = [(p.x, p.y) for p in e.points]
                    for nid, r in rects.items():
                        if nid in anc:
                            continue
                        box = (r.x + 0.5, r.y + 0.5,
                               r.x2 - 0.5, r.y2 - 0.5)
                        for i in range(len(pts) - 1):
                            assert not seg_enters_rect(
                                pts[i], pts[i + 1], box), (
                                f"{fname} {view}: {e.source_id}->"
                                f"{e.target_id} crosses {nid}")

    def test_no_grazes(self, corpus):
        """No graze: every segment keeps the corridor distance from
        every non-exempt node rect — near-corner grazing entries are a
        defect class (0.26.0 review, defect 4)."""
        for fname, views in corpus.items():
            for view, rl in views.items():
                rects = {}
                def walk(n):
                    rects[n.id] = n.rect
                    for c in n.children:
                        walk(c)
                for n in rl.layout.nodes:
                    walk(n)
                for e in rl.edges:
                    anc = _ancestors(rl.layout, e.source_id) \
                        | _ancestors(rl.layout, e.target_id) \
                        | {e.source_id, e.target_id}
                    pts = [(p.x, p.y) for p in e.points]
                    for nid, r in rects.items():
                        if nid in anc:
                            continue
                        box = (r.x, r.y, r.x2, r.y2)
                        for i in range(len(pts) - 1):
                            d = seg_box_dist(pts[i], pts[i + 1], box)
                            assert d >= CLEAR - 1e-6, (
                                f"{fname} {view}: {e.source_id}->"
                                f"{e.target_id} grazes {nid} "
                                f"({d:.2f} < {CLEAR})")

    def test_traceability_fields_on_routed_edges(self, corpus):
        """Every routed edge carries its direct border distance and
        path/direct ratio — the audit metrics that make this defect
        class measurable."""
        rl = corpus["juju4.ggarch"]["Data model"]
        e = _find_edge(rl, "endpoint_rec", "application_rec")
        sr = rl.layout.find("endpoint_rec").rect
        tr = rl.layout.find("application_rec").rect
        assert e.direct == pytest.approx(_border_direct(sr, tr), abs=0.5)
        expected = _path_len(e.points) / max(e.direct, 1.0)
        assert e.ratio == pytest.approx(expected, abs=0.01)


def _ancestors(layout, nid):
    """node id -> ancestor-or-self set (inclusive)."""
    out = set()
    def walk(n, chain):
        if n.id == nid:
            out.update(chain + [n.id])
            return True
        for c in n.children:
            if walk(c, chain + [n.id]):
                return True
        return False
    for n in layout.nodes:
        walk(n, [])
    return out


# ---------------------------------------------------------------------------
# Determinism across hash seeds (the kiwisolver-jitter trap)
# ---------------------------------------------------------------------------

_DETERMINISM_VIEWS = ("Data model", "Cross-model relation (CMR)",
                      "Intro: Juju enters", "HA controller: Dqlite replicaset")

_RUNNER = """\
import sys, json
sys.path.insert(0, {src!r})
from ggarch import parse, validate
from ggarch.solver import solve
from ggarch.router import route
f = parse(open({corpus!r}).read())
validate(f)
out = {{}}
for d in f.diagrams:
    if d.name not in {views!r}:
        continue
    m = f.get_model(d.model_name)
    rl = route(solve(d, m), m, d.select)
    for e in rl.edges:
        out[f"{{d.name}}|{{e.source_id}}|{{e.target_id}}"] = [
            (round(p.x, 4), round(p.y, 4)) for p in e.points]
print(json.dumps(out, sort_keys=True))
"""


@requires_corpus
class TestDeterminism:
    @pytest.mark.parametrize("seed", ["0", "1", "12345"])
    def test_routes_identical_across_hash_seeds(self, seed):
        """Routes are deterministic by construction: identical points
        across PYTHONHASHSEED values (the kiwisolver float-noise trap;
        the router's snapping is load-bearing)."""
        env = dict(os.environ, PYTHONHASHSEED=seed)
        chunks = []
        for fname in CORPUS_FILES:
            code = _RUNNER.format(
                src=os.path.join(os.path.expanduser("~"),
                                 "git", "ggarch", "src"),
                corpus=os.path.join(CORPUS, fname),
                views=_DETERMINISM_VIEWS)
            r = subprocess.run([sys.executable, "-c", code],
                               capture_output=True, text=True, env=env,
                               check=True)
            chunks.append(r.stdout)
        _seed_outputs[seed] = "\n".join(chunks)


_seed_outputs: dict = {}


@requires_corpus
class TestDeterminismCompare:
    def test_all_seeds_agree(self):
        assert len(_seed_outputs) == 3, _seed_outputs.keys()
        values = list(_seed_outputs.values())
        assert values[0] == values[1] == values[2], (
            "routes differ across hash seeds")


@requires_corpus
class TestGridAdjacency:
    def test_spine_relation_stacks_in_endpoints_column(self, corpus):
        """A cardinal constraint means ADJACENCY at the declared gap —
        the Scrabble rule (review round 4). The first cut drifted 475px
        away because left-of/below were pure inequalities and nothing
        pulled the free node toward its anchor; the weak adjacency pull
        pins it. Relation now hangs in endpoint's column (the column
        absorbs its satellite): vertical adjacency at the declared gap.
        The floor must also keep it OFF credential's cell — node
        overlap is the NOVER defect."""
        rl = corpus["juju3.ggarch"]["Data model (full spine)"]
        r = rl.layout.find("relation_rec").rect
        e = rl.layout.find("endpoint_rec").rect
        c = rl.layout.find("credential_rec").rect
        vgap = r.y - e.y2
        assert 50 <= vgap <= 120, f"relation drifted: vgap {vgap:.1f}"
        assert abs(r.cx - e.cx) <= 1.0, "not centred in the column"
        assert not (r.x < c.x2 and c.x < r.x2 and r.y < c.y2
                    and c.y < r.y2), "relation overlaps credential"
