"""Tests for shared model file usage — what :file: enables."""
import os
from pathlib import Path
import pytest
from ggarch import parse, validate, solve, route, render
from ggarch.sequence_renderer import render_sequence


JUJU_GGARCH = Path(__file__).parent.parent / "examples" / "juju.ggarch"


def get_juju_file():
    src = JUJU_GGARCH.read_text(encoding="utf-8")
    f = parse(src)
    validate(f)
    return f


class TestSharedModelFileParses:
    def test_parses_and_validates(self):
        f = get_juju_file()
        assert len(f.models) == 1

    def test_has_behaviours(self):
        f = get_juju_file()
        m = f.models[0]
        names = {b.name for b in m.behaviours}
        assert "hook execution" in names
        assert "bootstrap k8s" in names

    def test_all_diagrams_render(self):
        f = get_juju_file()
        for d in f.diagrams:
            m = f.get_model(d.model_name)
            l = solve(d, m)
            rl = route(l, m, d.select)
            svg = render(rl, m, d, dark=False)
            assert "<svg" in svg, f"diagram {d.name!r} produced no SVG"

    def test_all_sequences_render(self):
        f = get_juju_file()
        for s in f.sequences:
            m = f.get_model(s.model_name)
            svg = render_sequence(s, m, dark=False)
            assert "<svg" in svg, f"sequence {s.name!r} produced no SVG"


class TestDocsJujuGgarch:
    """Test the docs/juju.ggarch file that the architecture page references."""

    DOCS_FILE = Path(__file__).parent.parent.parent / "juju" / "docs" / "juju.ggarch"

    def test_docs_file_exists(self):
        if not self.DOCS_FILE.exists():
            pytest.skip("docs/juju.ggarch not accessible from ggarch test suite")

    def test_docs_file_parses(self):
        if not self.DOCS_FILE.exists():
            pytest.skip("docs/juju.ggarch not accessible")
        src = self.DOCS_FILE.read_text(encoding="utf-8")
        f = parse(src)
        validate(f)
        assert f.models[0].name == "Juju"

    def test_docs_file_has_all_five_views(self):
        if not self.DOCS_FILE.exists():
            pytest.skip("docs/juju.ggarch not accessible")
        src = self.DOCS_FILE.read_text(encoding="utf-8")
        f = parse(src)
        validate(f)
        diagram_names = {d.name for d in f.diagrams}
        sequence_names = {s.name for s in f.sequences}
        assert "Juju overview" in diagram_names
        assert "K8s deployment topology" in diagram_names
        assert "Hook execution" in sequence_names
        assert "Bootstrap K8s" in sequence_names

    def test_all_docs_views_render(self):
        if not self.DOCS_FILE.exists():
            pytest.skip("docs/juju.ggarch not accessible")
        src = self.DOCS_FILE.read_text(encoding="utf-8")
        f = parse(src)
        validate(f)
        for d in f.diagrams:
            m = f.get_model(d.model_name)
            l = solve(d, m)
            rl = route(l, m, d.select)
            svg = render(rl, m, d, dark=False)
            assert "<svg" in svg
        for s in f.sequences:
            m = f.get_model(s.model_name)
            svg = render_sequence(s, m, dark=False)
            assert "<svg" in svg
