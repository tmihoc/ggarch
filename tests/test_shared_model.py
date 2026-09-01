"""Tests for example .ggarch files — one test class per file."""
from pathlib import Path
import pytest
from ggarch import parse, validate, solve, route, render
from ggarch.sequence_renderer import render_sequence

EXAMPLES = Path(__file__).parent.parent / "examples"


def _load(name: str):
    src = (EXAMPLES / name).read_text(encoding="utf-8")
    f = parse(src)
    validate(f)
    return f


def _render_all(f):
    svgs = []
    for d in f.diagrams:
        m = f.get_model(d.model_name)
        svgs.append(render(route(solve(d, m), m, d.select), m, d))
    for s in f.sequences:
        svgs.append(render_sequence(s, f.get_model(s.model_name)))
    return svgs


class TestTopologyExample:
    """topology.ggarch — nested containers, typed edges, lifecycle, cardinality."""
    F = "topology.ggarch"

    def test_parses_and_validates(self):
        _load(self.F)

    def test_has_topology_diagrams(self):
        f = _load(self.F)
        names = {d.name for d in f.diagrams}
        assert "K8s deployment topology" in names
        assert "Unit focus" in names

    def test_renders_svg(self):
        svgs = _render_all(_load(self.F))
        assert all("<svg" in s for s in svgs)

    def test_has_init_lifecycle_nodes(self):
        f = _load(self.F)
        m = f.models[0]
        init_nodes = [n for n in m.nodes
                      if any(c.lifecycle.value == "init"
                             for c in n.children)]
        assert init_nodes, "expected init-lifecycle nodes in controller_pod"


class TestCollapseExpandExample:
    """collapse-expand.ggarch — selective zoom (collapse/expand)."""
    F = "collapse-expand.ggarch"

    def test_parses_and_validates(self):
        _load(self.F)

    def test_has_collapse_in_select(self):
        f = _load(self.F)
        d = f.diagrams[0]
        assert "controller_pod" in d.select.collapse

    def test_renders_svg(self):
        svgs = _render_all(_load(self.F))
        assert all("<svg" in s for s in svgs)


class TestInstancesExample:
    """instances.ggarch — type instantiation (one type, multiple instances)."""
    F = "instances.ggarch"

    def test_parses_and_validates(self):
        _load(self.F)

    def test_has_instances_in_select(self):
        f = _load(self.F)
        d = f.diagrams[0]
        assert len(d.select.instances) == 2
        labels = {inst.label for inst in d.select.instances}
        assert "postgresql/0" in labels
        assert "pgbouncer/0" in labels

    def test_renders_svg(self):
        svgs = _render_all(_load(self.F))
        assert all("<svg" in s for s in svgs)


class TestSequenceExample:
    """sequence.ggarch — sequence diagram (call/return/async/loop/alt)."""
    F = "sequence.ggarch"

    def test_parses_and_validates(self):
        _load(self.F)

    def test_has_two_sequences(self):
        f = _load(self.F)
        names = {s.name for s in f.sequences}
        assert "Hook execution" in names
        assert "Bootstrap K8s" in names

    def test_renders_svg_light_and_dark(self):
        f = _load(self.F)
        s = f.sequences[0]
        m = f.get_model(s.model_name)
        light = render_sequence(s, m, dark=False)
        dark  = render_sequence(s, m, dark=True)
        assert "<svg" in light
        assert "<svg" in dark
        assert light != dark

    def test_loop_and_alt_in_svg(self):
        f = _load(self.F)
        s = f.sequences[0]
        m = f.get_model(s.model_name)
        svg = render_sequence(s, m)
        assert "during hook" in svg
        assert "exit 0"     in svg
        assert "failure"    in svg


class TestSequenceParOptExample:
    """sequence-par-opt.ggarch — par lanes, opt block, activation bars."""
    F = "sequence-par-opt.ggarch"

    def test_parses_and_validates(self):
        _load(self.F)

    def test_par_and_opt_in_svg(self):
        f = _load(self.F)
        s = f.sequences[0]
        m = f.get_model(s.model_name)
        svg = render_sequence(s, m)
        assert "[par]" in svg
        assert "[opt]" in svg
        assert "if data changed" in svg

    def test_activation_bar_in_svg(self):
        f = _load(self.F)
        s = f.sequences[0]
        m = f.get_model(s.model_name)
        svg = render_sequence(s, m)
        assert "#CCCCEE" in svg  # activation bar fill (light mode)

    def test_par_green_tint(self):
        f = _load(self.F)
        s = f.sequences[0]
        m = f.get_model(s.model_name)
        svg = render_sequence(s, m)
        assert "#66AA66" in svg  # par lane stroke colour


class TestErDiagramExample:
    """er-diagram.ggarch — record nodes, PK/FK markers, field-qualified edges."""
    F = "er-diagram.ggarch"

    def test_parses_and_validates(self):
        _load(self.F)

    def test_five_record_tables(self):
        f = _load(self.F)
        m = f.models[0]
        records = [n for n in m.nodes if n.type == "record"]
        assert len(records) == 5

    def test_field_qualified_edges(self):
        f = _load(self.F)
        m = f.models[0]
        qualified = [e for e in m.edges if e.source_field or e.target_field]
        assert len(qualified) == 4

    def test_pk_fk_nullable_in_svg(self):
        svgs = _render_all(_load(self.F))
        svg = svgs[0]
        assert "PK"         in svg
        assert "FK"         in svg
        assert "provider_id?" in svg  # nullable field

    def test_renders_light_and_dark(self):
        f = _load(self.F)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        rl = route(solve(d, m), m, d.select)
        light = render(rl, m, d, dark=False)
        dark  = render(rl, m, d, dark=True)
        assert "<svg" in light
        assert light != dark


class TestClassDiagramExample:
    """class-diagram.ggarch — class nodes, visibility markers, inheritance edges."""
    F = "class-diagram.ggarch"

    def test_parses_and_validates(self):
        _load(self.F)

    def test_four_class_nodes(self):
        f = _load(self.F)
        m = f.models[0]
        classes = [n for n in m.nodes if n.type == "class"]
        assert len(classes) == 4

    def test_visibility_markers_in_svg(self):
        svgs = _render_all(_load(self.F))
        svg = svgs[0]
        assert "+" in svg   # public
        assert "-" in svg   # private
        assert "#" in svg   # protected

    def test_inheritance_labels_in_svg(self):
        svgs = _render_all(_load(self.F))
        svg = svgs[0]
        assert "implements" in svg
        assert "extends"    in svg

    def test_renders_svg(self):
        svgs = _render_all(_load(self.F))
        assert all("<svg" in s for s in svgs)


class TestDocsJujuGgarch:
    """Test the docs/juju.ggarch file that the architecture page references."""

    DOCS_FILE = Path(__file__).parent.parent.parent / "juju" / "docs" / "juju.ggarch"

    def test_docs_file_parses(self):
        if not self.DOCS_FILE.exists():
            pytest.skip("docs/juju.ggarch not accessible")
        f = parse(self.DOCS_FILE.read_text(encoding="utf-8"))
        validate(f)
        assert f.models[0].name == "Juju"

    def test_docs_file_has_key_views(self):
        if not self.DOCS_FILE.exists():
            pytest.skip("docs/juju.ggarch not accessible")
        f = parse(self.DOCS_FILE.read_text(encoding="utf-8"))
        validate(f)
        assert "Juju overview"          in {d.name for d in f.diagrams}
        assert "K8s deployment topology" in {d.name for d in f.diagrams}
        assert "Hook execution"          in {s.name for s in f.sequences}

    def test_all_docs_views_render(self):
        if not self.DOCS_FILE.exists():
            pytest.skip("docs/juju.ggarch not accessible")
        f = parse(self.DOCS_FILE.read_text(encoding="utf-8"))
        validate(f)
        for d in f.diagrams:
            m = f.get_model(d.model_name)
            assert "<svg" in render(route(solve(d, m), m, d.select), m, d)
        for s in f.sequences:
            assert "<svg" in render_sequence(s, f.get_model(s.model_name))
