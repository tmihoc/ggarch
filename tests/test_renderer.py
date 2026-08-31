"""Renderer tests — SVG output validation."""
import pytest
from ggarch import parse, validate
from ggarch.solver import solve
from ggarch.router import route
from ggarch.renderer import render, render_both


def pipeline(src: str, view_name: str | None = None, dark: bool = False) -> str:
    f = parse(src)
    validate(f)
    diagram = f.diagrams[0] if not view_name else next(
        d for d in f.diagrams if d.name == view_name
    )
    model = f.get_model(diagram.model_name)
    layout = solve(diagram, model)
    rl = route(layout, model, diagram.select)
    return render(rl, model, diagram, dark=dark)


SIMPLE = """\
model "M" {
  nodes {
    a [type: juju-software, label: "Controller"]
    b [type: charm, label: "Charm"]
  }
  edges {
    a -> b [type: control, label: "exec dispatch"]
  }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 40 }
}
"""


class TestSVGStructure:
    def test_produces_svg_element(self):
        svg = pipeline(SIMPLE)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_has_node_group(self):
        svg = pipeline(SIMPLE)
        assert 'id="ggarch-nodes"' in svg

    def test_has_edge_group(self):
        svg = pipeline(SIMPLE)
        assert 'id="ggarch-edges"' in svg

    def test_has_annotation_group(self):
        svg = pipeline(SIMPLE)
        assert 'id="ggarch-annotations"' in svg

    def test_has_arrowhead_marker(self):
        svg = pipeline(SIMPLE)
        assert 'id="arrow"' in svg

    def test_has_viewbox(self):
        svg = pipeline(SIMPLE)
        assert "viewBox" in svg or "width" in svg


class TestNodeRendering:
    def test_label_text_present(self):
        svg = pipeline(SIMPLE)
        assert "Controller" in svg
        assert "Charm" in svg

    def test_orange_fill_for_juju_software(self):
        svg = pipeline(SIMPLE)
        assert "#E95420" in svg

    def test_dark_mode_different_background(self):
        light = pipeline(SIMPLE, dark=False)
        dark  = pipeline(SIMPLE, dark=True)
        assert "#1E1E2E" in dark
        assert "#FFFFFF" in light

    def test_render_both_returns_two_strings(self):
        f = parse(SIMPLE)
        validate(f)
        diagram = f.diagrams[0]
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        rl = route(layout, model, diagram.select)
        light, dark = render_both(rl, model, diagram)
        assert "<svg" in light
        assert "<svg" in dark
        assert light != dark

    def test_container_node_renders(self):
        src = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      agent [type: juju-software, label: "Agent"]
    }
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: pod }
}
"""
        svg = pipeline(src)
        assert "Pod" in svg
        assert "Agent" in svg

    def test_lifecycle_init_dashed_stroke(self):
        src = """\
model "M" {
  nodes {
    x [type: juju-software, label: "Init", lifecycle: init]
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: x }
}
"""
        svg = pipeline(src)
        # Init lifecycle should produce a dashed stroke.
        assert "stroke-dasharray" in svg or "dasharray" in svg

    def test_cylinder_shape_for_database(self):
        src = """\
model "M" {
  nodes {
    db [type: database, label: "DB"]
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: db }
}
"""
        svg = pipeline(src)
        # Cylinder uses ellipse elements.
        assert "<ellipse" in svg

    def test_person_shape(self):
        src = """\
model "M" {
  nodes {
    u [type: person, label: "User"]
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: u }
}
"""
        svg = pipeline(src)
        assert "User" in svg
        assert "<circle" in svg


class TestEdgeRendering:
    def test_edge_path_present(self):
        svg = pipeline(SIMPLE)
        assert "<path" in svg

    def test_edge_label_present(self):
        svg = pipeline(SIMPLE)
        assert "exec dispatch" in svg

    def test_stream_edge_dashed(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges { a -> b [type: stream, label: "watch"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 40 }
}
"""
        svg = pipeline(src)
        assert "dasharray" in svg

    def test_forward_arrow_marker(self):
        svg = pipeline(SIMPLE)
        assert "marker-end" in svg or "marker_end" in svg


class TestAnnotationRendering:
    def test_box_annotation_renders(self):
        src = """\
model "M" {
  nodes {
    a [type: juju-software, label: "A"]
    b [type: juju-software, label: "B"]
  }
  edges { a -> b [type: api, label: "x"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 40 }
  annotations {
    box [nodes: "a b", label: "group", style: dashed, color: "#E95420"]
  }
}
"""
        svg = pipeline(src)
        assert "group" in svg
        assert "#E95420" in svg

    def test_badge_annotation_renders(self):
        src = """\
model "M" {
  nodes {
    a [type: juju-software, label: "A"]
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: a }
  annotations {
    badge [anchor: a, text: "(init)"]
  }
}
"""
        svg = pipeline(src)
        assert "(init)" in svg


class TestJujuRender:
    def test_k8s_topology_renders_light(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
        svg = pipeline(src, "K8s deployment topology", dark=False)
        assert "<svg" in svg
        assert "Controller pod" in svg
        assert "Unit pod" in svg

    def test_k8s_topology_renders_dark(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
        svg = pipeline(src, "K8s deployment topology", dark=True)
        assert "<svg" in svg
        assert "#1E1E2E" in svg

    def test_unit_focus_renders(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
        svg = pipeline(src, "Unit focus", dark=False)
        assert "Unit agent" in svg
        assert "Charm" in svg
