"""A container pads its children where a label needs room, and no more.

The top pad carries the container's label band. The bottom and side pads have
no label, so they are the plain container padding: a nested box does not float
in empty space under its content (Juju docs, Storage pool figure, 2026-11-27).
"""
from ggarch.layout import CONTAINER_BOTTOM_PAD, CONTAINER_PAD, CONTAINER_PAD_TOP
from ggarch.parser import parse
from ggarch.solver import solve

SRC = """\
model "M" {
  nodes {
    box [type: entity, label: "Box"] {
      inner [type: entity, label: "Inner"]
    }
    out [type: external, label: "Out"]
  }
  edges { inner -> out [type: api, label: "x"] }
  style { extends: juju }
}
diagram "D" from "M" {
  select { nodes: box out edges: type api }
  positions { out right-of box gap: 60 }
}
"""


def test_bottom_pad_is_the_plain_padding_not_the_label_band():
    f = parse(SRC)
    layout = solve(f.diagrams[0], f.models[0])
    box = next(n for n in layout.nodes if n.id == "box")
    inner = box.children[0]
    top = inner.rect.y - box.rect.y
    bottom = (box.rect.y + box.rect.h) - (inner.rect.y + inner.rect.h)
    side = inner.rect.x - box.rect.x
    assert top >= CONTAINER_PAD_TOP
    assert bottom == CONTAINER_BOTTOM_PAD
    assert bottom <= CONTAINER_PAD
    assert side == CONTAINER_PAD
    assert bottom < top


UNLABELLED = SRC.replace('box [type: entity, label: "Box"]', 'box [type: entity, label: ""]')


def test_a_container_without_a_label_pads_its_top_like_its_sides():
    f = parse(UNLABELLED)
    layout = solve(f.diagrams[0], f.models[0])
    box = next(n for n in layout.nodes if n.id == "box")
    inner = box.children[0]
    assert inner.rect.y - box.rect.y == CONTAINER_PAD
    assert inner.rect.x - box.rect.x == CONTAINER_PAD


ALONE = """\
model "M" {
  nodes {
    box [type: entity, label: "Box"] {
      a [type: entity, label: "A"]
      b [type: entity, label: "B"]
    }
  }
  edges { a -> b [type: api, label: "x"] }
  style { extends: juju }
}
diagram "D" from "M" {
  select { nodes: box edges: type api }
}
"""


def test_a_single_container_with_internal_edges_is_not_an_orphan():
    from ggarch.validator import validate
    f = parse(ALONE)
    validate(f)
    layout = solve(f.diagrams[0], f.models[0])
    assert [n.id for n in layout.nodes] == ["box"]


LABELLED_BOX = """\
model "M" {
  nodes {
    a [type: entity, label: "A"]
    b [type: entity, label: "B"]
  }
  edges { a -> b [type: api, label: "x"] }
  style { extends: juju }
}
diagram "D" from "M" {
  select { nodes: a b edges: type api }
  positions { b right-of a gap: 40 }
  annotations {
    box [nodes: "a b", label: "Group", style: "solid", color: "#B4B4B4",
         label-color: "text", label-style: "italic"]
  }
}
"""


def test_a_box_label_can_be_italic_and_readable_on_a_pale_border():
    from ggarch.renderer import render
    from ggarch.router import route
    from ggarch.validator import validate
    f = parse(LABELLED_BOX)
    validate(f)
    d, m = f.diagrams[0], f.models[0]
    svg = render(route(solve(d, m), m, d.select), m, d)
    svg = svg if isinstance(svg, str) else str(svg)
    assert 'font-style="italic"' in svg
    assert "#595959" in svg
