"""Regression tests for collective nodes and the view zoom (2026-09-22).

Two language features built for the tutorial's progressive reveal:
- `collective:` on a node — the node abstracts over the instances of
  its base kind; the renderer draws the overlapping-rectangles stack
  behind the box (the Mermaid/Structurizr plurality mark). The glyph
  is a drawing-layer idiom: no anchor moves, no measurement changes,
  the audit sees the same geometry. Validation: the base kind must
  exist in the model.
- `zoom: N` on a select — the children's-book scale (reviewer:
  "printing for children — bigger and brighter on purpose"). A PURE
  root transform: the SVG's pixel dimensions grow by N, the viewBox
  and all coordinates stay put, so corridors and clash invariants
  hold unchanged.
"""
import re
import textwrap

import pytest

from ggarch import parse, validate
from ggarch.errors import ValidationError
from ggarch.solver import solve
from ggarch.router import route
from ggarch.renderer import render

MODEL_NODES = """
model "Z" {
  nodes {
    a [type: external, label: "A"]
    unit [type: charm, label: "Unit kind"]
    b [type: charm, label: "Many units", collective: unit]
  }
  edges {
    a -> b [type: api]
  }
}
"""


def _diagram(*views: str) -> str:
    return MODEL_NODES + "\n" + "\n".join(views) + "\n"


def _render(f, name):
    from ggarch.solver import solve
    from ggarch.router import route
    from ggarch.renderer import render
    d = next(x for x in f.diagrams if x.name == name)
    m = f.get_model("Z")
    return render(route(solve(d, m), m, d.select), m, d), solve(d, m)


def test_collective_and_zoom_parse_and_validate():
    f = parse(_diagram(
        'diagram "v" from "Z" {\n'
        '  select { nodes: a b\n'
        '           edges: type api\n'
        '           zoom: 1.3 } \n'
        '}'))
    validate(f)
    d = f.diagrams[0]
    assert d.select.zoom == pytest.approx(1.3)


def test_zoom_scales_pixels_not_geometry():
    f = parse(_diagram(
        'diagram "plain" from "Z" {\n'
        '  select { nodes: a b\n'
        '           edges: type api } \n'
        '}\n'
        'diagram "zoomed" from "Z" {\n'
        '  select { nodes: a b\n'
        '           edges: type api\n'
        '           zoom: 1.5 } \n'
        '}'))
    svg_plain, _ = _render(f, "plain")
    svg_zoom, s_zoom = _render(f, "zoomed")
    assert _svg_width(svg_zoom) == pytest.approx(_svg_width(svg_plain) * 1.5)
    # geometry unchanged: the same node rects solve under both views
    # (same model, only the select's zoom differs)
    plain = next(x for x in f.diagrams if x.name == "plain")
    rects_zoom = [(round(n.rect.x, 1), round(n.rect.y, 1),
                   round(n.rect.w, 1), round(n.rect.h, 1)) for n in s_zoom.nodes]
    rects_plain = [(round(n.rect.x, 1), round(n.rect.y, 1),
                    round(n.rect.w, 1), round(n.rect.h, 1))
                   for n in solve(plain, f.get_model("Z")).nodes]
    assert rects_zoom == rects_plain


def _svg_width(svg: str) -> float:
    return float(re.search(r'width="([\d.]+)"', svg).group(1))


def test_collective_draws_the_stack_mark():
    f = parse(_diagram(
        'diagram "v" from "Z" {\n'
        '  select { nodes: a b\n'
        '           edges: type api } \n'
        '}'))
    svg, solved = _render(f, "v")
    b = solved.find("b")
    # the mark layers live in SVG space (canvas origin shifted); the
    # chain is identified by b's own box size: exactly three rects
    # share b's (width, height) — two mark layers + the box — and
    # they step by (-5, +5), the box drawn LAST (the marks behind).
    rects = re.findall(
        r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg)
    chain = [(float(x), float(y))
             for x, y, w, h in rects
             if round(float(w), 1) == round(b.rect.w, 1)
             and round(float(h), 1) == round(b.rect.h, 1)]
    assert len(chain) == 3, chain
    steps = [(round(chain[i + 1][0] - chain[i][0], 1),
              round(chain[i + 1][1] - chain[i][1], 1)) for i in (0, 1)]
    assert steps == [(-5.0, 5.0), (-5.0, 5.0)], steps


def test_collective_base_kind_must_exist():
    bad = textwrap.dedent("""
    model "Z" {
      nodes {
        a [type: external, label: "A"]
        b [type: charm, label: "Many", collective: nope]
      }
      edges {
        a -> b [type: api]
      }
    }
    """).strip() + "\n"
    with pytest.raises(ValidationError):
        validate(parse(bad))

def test_labels_hidden_suppresses_labels_before_routing():
    """`labels: hidden` blanks every edge label BEFORE routing — the
    router prices label-free corridors, so the diagram gets genuinely
    lighter (the reviewer's teaching-diagram ask), not just visually
    muted. The model keeps its labels; other views keep theirs."""
    f = parse(_diagram(
        'diagram "v" from "Z" {\n'
        '  select { nodes: a b\n'
        '           edges: type api\n'
        '           labels: hidden } \n'
        '}'))
    validate(f)
    svg, solved = _render(f, "v")
    assert svg.count("textPath") == 0
    from ggarch.router import route as _route
    r = _route(solve(next(x for x in f.diagrams if x.name == "v"),
                     f.get_model("Z")), f.get_model("Z"),
               next(x for x in f.diagrams if x.name == "v").select)
    assert all(e.label == "" for e in r.edges)
    assert all(e.strip is None or e.strip.label is None for e in r.edges)
