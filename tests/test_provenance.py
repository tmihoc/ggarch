"""ADR-005 — provenance v2: chips derive, bridges render.

The chip's text derives from the record's storage truth (DDL ground,
falling back to the label); the ggarch node id never reaches the
canvas. Chips are upward-closed: a container whose subtree records
storage shows the derived chip. `records: shown` renders the
runtime→record bridge as a synthetic view edge (amber, headless) and
auto-includes the record node.
"""
import pytest
from ggarch import parse, validate, solve, route, render
from ggarch.errors import ValidationError


def _svg(src: str, dark: bool = False) -> str:
    f = parse(src)
    validate(f)
    d = f.diagrams[0]
    m = f.get_model(d.model_name)
    return render(route(solve(d, m), m, d.select), m, d, dark=dark)


BASE = """\
model "M" {
  nodes {
    pod [type: container, label: "Unit pod"] {
      ua [type: juju-software, label: "UA", records: "unit_rec"]
    }
    unit_rec [type: record, label: "unit"]
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: pod unit_rec }
  positions { pod left-of unit_rec gap: 80 }
}
"""


class TestDerivedChips:
    def test_chip_shows_record_label_not_id(self):
        """Ungrounded record: the chip carries the record's label; the
        ggarch node id never reaches the canvas."""
        svg = _svg(BASE)
        assert "rec:" not in svg
        assert "unit_rec" not in svg

    def test_chip_shows_ddl_ground_when_grounded(self):
        """A grounded record: the chip is the DDL string check-grounding
        verifies."""
        src = BASE.replace(
            'unit_rec [type: record, label: "unit"]',
            'unit_rec [type: record, label: "unit", '
            'ground: "model:units"]')
        svg = _svg(src)
        assert "model:units" in svg

    def test_chip_is_upward_closed(self):
        """The pod declares nothing; its agent does. The pod shows the
        derived chip anyway (the hand-omission failure mode is
        abolished)."""
        svg = _svg(BASE)
        # The pod renders before its children (containers first); both
        # carry the pill — count two.
        assert svg.count("rx=\"3\" ry=\"3\"") >= 2

    def test_multi_line_label_uses_first_line(self):
        src = BASE.replace(
            'unit_rec [type: record, label: "unit"]',
            'unit_rec [type: record, label: "unit\\n(uuid, name)"]')
        f = parse(src)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        text = None
        from ggarch.renderer import _derived_records_chip
        text = _derived_records_chip("unit_rec", m)
        assert text == "unit"


class TestRecordsBridge:
    BRIDGE_SRC = BASE.replace(
        "select { nodes: pod unit_rec }",
        "select { nodes: pod  records: shown }")

    def test_bridge_renders_when_shown(self):
        svg = _svg(self.BRIDGE_SRC)
        assert 'marker-end' not in svg.split("ggarch-annotations")[0] \
            or "url(#arrow" not in svg  # headless
        assert "#F9A825" in svg  # amber bridge stroke

    def test_bridge_auto_includes_record_node(self):
        """The record node lays out even though the select names only
        the pod."""
        f = parse(self.BRIDGE_SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        layout = solve(d, m)
        assert layout.find("unit_rec") is not None

    def test_no_bridge_by_default(self):
        """Without `records: shown`, existing views are untouched: no
        bridge edge is routed."""
        f = parse(BASE)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        rl = route(solve(d, m), m, d.select)
        assert not [e for e in rl.edges if e.edge_type == "records"]

    def test_bridge_is_headless_and_routed(self):
        f = parse(self.BRIDGE_SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        rl = route(solve(d, m), m, d.select)
        bridges = [e for e in rl.edges if e.edge_type == "records"]
        assert len(bridges) == 1
        assert bridges[0].arrow == "none"
        assert bridges[0].source_id == "ua"
        assert bridges[0].target_id == "unit_rec"

    def test_records_not_declarable_as_model_edge_type(self):
        """The bridge is a rendering, not a model edge type: hand-
        declaring `type: records` stays a validation error."""
        src = BASE.replace("edges {}", "edges { pod -> unit_rec [type: records] }")
        f = parse(src)
        with pytest.raises(ValidationError, match="unknown type"):
            validate(f)
