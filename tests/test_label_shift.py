"""Regression tests for the along-leg label shift (2026-09-22).

The labels-NEVER-overlap law owns the shift pass's candidate check but
not (until 2026-09-22) its trigger — and the candidate acceptance's
"own container" exemption degenerated for top-level nodes (the node's
box contains itself), so a shift candidate could slide a label over
the arrowhead INTO the target's node space — measured on the declared
"Juju enters": app2's label drawn half inside the controller box
("stat" hidden behind the node) while the measured strip said the
arrow tip was clear. Contract pinned here: a shift never MOVES a
label into a node box; route-time strips are not asserted (their
padded corners may graze their own endpoints without touching
glyphs — the corpus's accepted baseline).
"""
import os

import pytest

from ggarch import parse, validate
from ggarch.solver import solve
from ggarch.router import route
from ggarch.renderer import render, rects_overlap

CORPUS = os.path.join(os.path.expanduser("~"), "git", "juju", "docs")

requires_corpus = pytest.mark.skipif(
    not os.path.exists(os.path.join(CORPUS, "juju.ggarch")),
    reason="juju docs corpus not present")


def _load(name):
    with open(os.path.join(CORPUS, name)) as fh:
        f = parse(fh.read())
    validate(f)
    return f


@pytest.mark.parametrize("file_name,view_name", [
    ("juju.ggarch", "Intro: Juju enters"),
    ("juju.ggarch", "Intro: Juju enters (declared)"),
])
@requires_corpus
def test_shift_never_moves_label_onto_own_endpoint(file_name, view_name):
    f = _load(file_name)
    d = next(x for x in f.diagrams if x.name == view_name)
    m = f.get_model(d.model_name)
    r = route(solve(d, m), m, d.select)
    render(r, m, d)
    boxes = {n.id: (n.rect.x, n.rect.y, n.rect.x2, n.rect.y2)
             for n in r.layout.nodes}
    for e in r.edges:
        if e.label_anchor == 0.5:
            continue            # not shifted: the route-time baseline
        strip = e.strip.label
        if strip is None:
            continue
        for nid in (e.source_id, e.target_id):
            nb = boxes.get(nid)
            assert nb is None or not rects_overlap(strip, nb), (
                f"{file_name} {view_name}: the shift moved "
                f"{e.source_id}->{e.target_id}'s label (frac "
                f"{round(e.label_anchor, 2)}) to strip "
                f"{tuple(round(v, 1) for v in e.strip.label)} overlapping "
                f"its own endpoint {nid}")