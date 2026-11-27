"""Ports: labelled sockets on a node's border that edges end on."""
import pytest

from ggarch import parse, render, route, solve, validate
from ggarch.errors import ValidationError
from ggarch.layout import PORT_SIZE, port_center, port_node_min_size

SRC = """\
model "M" {
  nodes {
    offer [type: entity, label: "Offer"]
    app [type: entity, label: "Application"] {
      ports {
        a [label: "Endpoint A"]
        b [label: "Endpoint B"]
        c [label: "Endpoint C"]
      }
    }
  }
  edges {
    offer -> app.a [type: control, label: "includes"]
    offer -> app.b [type: control]
  }
  style { extends: juju }
}
diagram "D" from "M" {
  select { nodes: offer app  edges: type control }
  positions {
    offer left-of app gap: 90
    offer align-middle app
  }
}
"""


def _model(src=SRC):
    """Parse and validate; return (diagram, model)."""
    f = parse(src)
    validate(f)
    d = f.diagrams[0]
    return d, f.get_model(d.model_name)


def _solved(src=SRC):
    d, m = _model(src)
    layout = solve(d, m)
    return d, m, layout, route(layout, m, d.select)


def _bad(body: str, edges: str = "") -> str:
    return f"""\
model "M" {{
  nodes {{
    x [type: entity, label: "X"]
    app [type: entity, label: "App"] {{
{body}
    }}
  }}
  edges {{
{edges}
  }}
}}
"""


def test_ports_parse_with_left_default_and_explicit_side():
    f = parse(SRC.replace('c [label: "Endpoint C"]', 'c [label: "Endpoint C", side: right]'))
    app = next(n for n in f.models[0].nodes if n.id == "app")
    assert [(p.id, p.port, p.side) for p in app.fields] == [
        ("a", True, "left"), ("b", True, "left"), ("c", True, "right")]


@pytest.mark.parametrize("body,edges,message", [
    ('ports { a [label: "A"]  a [label: "A2"] }', "", "duplicate port id 'a'"),
    ('ports { a [label: "A", side: middle] }', "", "has side 'middle'"),
    ('ports { a [label: "A"] }\n      fields { f [label: "f"] }', "", "both ports and fields"),
    ('ports { y [label: "Y"] }\n      y [type: entity, label: "Y"]', "", "ports go on a leaf node"),
    ('fields { f [label: "f", side: left] }', "", "only ports take one"),
    ('ports { a [label: "A"] }', "x -> app.z [type: control]", "undeclared field or port"),
])
def test_port_validation_errors(body, edges, message):
    with pytest.raises(ValidationError, match=message):
        validate(parse(_bad(body, edges)))


def test_node_grows_to_fit_its_ports():
    d, m = _model()
    layout = solve(d, m)
    app = layout.find("app")
    min_w, min_h = port_node_min_size(app.label, app.fields)
    assert app.rect.h >= min_h and app.rect.w >= min_w
    # Three left ports need more height than the plain label box would.
    assert min_h > 3 * 30


def test_edges_end_on_the_outer_face_of_their_port_and_arrive_level():
    _d, _m, layout, routed = _solved()
    app = layout.find("app")
    for port_id in ("a", "b"):
        edge = next(e for e in routed.edges if e.target_id == "app"
                    and abs(e.points[-1].y - port_center(app.rect, app.fields, port_id)[1]) < 0.5)
        cx, cy, side = port_center(app.rect, app.fields, port_id)
        end, before = edge.points[-1], edge.points[-2]
        assert side == "left"
        assert end.x == pytest.approx(cx - PORT_SIZE / 2)
        assert end.y == pytest.approx(cy)
        assert before.y == pytest.approx(end.y)          # horizontal approach
        assert before.x < end.x                           # from the outside


def test_rendered_svg_draws_every_port_and_its_label():
    d, m, _layout, routed = _solved()
    for dark in (False, True):
        svg = render(routed, m, d, dark=dark)
        for label in ("Endpoint A", "Endpoint B", "Endpoint C"):
            assert label in svg
        squares = [ln for ln in svg.split("<rect")
                   if f'width="{PORT_SIZE}"' in ln and f'height="{PORT_SIZE}"' in ln]
        assert len(squares) == 3


def test_fields_hidden_view_keeps_ports():
    src = SRC.replace("edges: type control }", "edges: type control  fields: hidden }")
    d, m = _model(src)
    layout = solve(d, m)
    assert [p.id for p in layout.find("app").fields] == ["a", "b", "c"]
