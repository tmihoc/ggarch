"""Tests for Phase 10: properties/url on model entities; legend annotation."""
import pytest
from ggarch import parse, validate, solve, route, render


PROPS_SRC = """\
model "M" {
  nodes {
    svc [type: juju-software, label: "Service",
         url: "https://example.com",
         team: "platform", tier: "backend"]
    db  [type: database,      label: "DB",
         url: "https://db.example.com"]
  }
  edges {
    svc -> db [type: data, label: "query",
               url: "https://api.example.com",
               rps: "1000"]
  }
  style { extends: juju }
}
diagram "D" from "M" {
  select { nodes: svc db }
  positions { svc left-of db gap: 60  svc align-middle db }
}
"""

LEGEND_SRC = """\
model "M" {
  nodes {
    a [type: juju-software, label: "Agent"]
    b [type: external,      label: "Cloud"]
  }
  edges { a -> b [type: control] }
  style { extends: juju }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 60  a align-middle b }
  annotations {
    legend [position: "bottom-right"]
  }
}
"""


def _pipeline(src, dark=False):
    f = parse(src); validate(f)
    d = f.diagrams[0]; m = f.get_model(d.model_name)
    return render(route(solve(d, m), m, d.select), m, d, dark=dark)


class TestPropertiesParsing:
    def test_node_url_parsed(self):
        f = parse(PROPS_SRC)
        n = f.models[0].find_node("svc")
        assert n.url == "https://example.com"

    def test_node_properties_parsed(self):
        f = parse(PROPS_SRC)
        n = f.models[0].find_node("svc")
        assert n.properties.get("team") == "platform"
        assert n.properties.get("tier") == "backend"

    def test_node_known_attrs_not_in_properties(self):
        f = parse(PROPS_SRC)
        n = f.models[0].find_node("svc")
        assert "label" not in n.properties
        assert "type" not in n.properties

    def test_edge_url_parsed(self):
        f = parse(PROPS_SRC)
        e = f.models[0].edges[0]
        assert e.url == "https://api.example.com"

    def test_edge_properties_parsed(self):
        f = parse(PROPS_SRC)
        e = f.models[0].edges[0]
        assert e.properties.get("rps") == "1000"

    def test_validates_cleanly(self):
        f = parse(PROPS_SRC); validate(f)


class TestUrlInSvg:
    def test_node_url_in_svg(self):
        svg = _pipeline(PROPS_SRC)
        # drawsvg renders Hyperlink as <a href="...">
        assert "https://example.com" in svg

    def test_svg_renders(self):
        svg = _pipeline(PROPS_SRC)
        assert "<svg" in svg


class TestLegendAnnotation:
    def test_legend_parses(self):
        f = parse(LEGEND_SRC); validate(f)
        from ggarch.model import AnnotationLegend
        d = f.diagrams[0]
        assert any(isinstance(a, AnnotationLegend) for a in d.annotations)

    def test_legend_position_default(self):
        f = parse(LEGEND_SRC)
        from ggarch.model import AnnotationLegend
        leg = next(a for a in f.diagrams[0].annotations
                   if isinstance(a, AnnotationLegend))
        assert leg.position == "bottom-right"

    def test_legend_renders_node_type_labels(self):
        svg = _pipeline(LEGEND_SRC)
        assert "juju-software" in svg or "external" in svg

    def test_legend_renders_edge_type_labels(self):
        svg = _pipeline(LEGEND_SRC)
        assert "control" in svg

    def test_legend_bare_syntax(self):
        src = LEGEND_SRC.replace(
            'legend [position: "bottom-right"]', "legend"
        )
        f = parse(src); validate(f)
        from ggarch.model import AnnotationLegend
        assert any(isinstance(a, AnnotationLegend) for a in f.diagrams[0].annotations)

    def test_legend_dark_mode(self):
        svg = _pipeline(LEGEND_SRC, dark=True)
        assert "<svg" in svg
        assert "#1E1E2E" in svg
