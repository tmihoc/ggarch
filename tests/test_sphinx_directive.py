"""Sphinx directive integration tests.

Runs a real (minimal) Sphinx build against the {ggarch} directive -- the
only coverage that exercises the directive, slideshow, and state-view
resolution paths end to end.
"""
import pytest


STATE_MODEL = """\
model "M" {
  nodes {
    idle    [type: juju-software, label: "Idle"]
    running [type: juju-software, label: "Running"]
  }
  edges {
    idle    -> running [type: control]
    running -> idle    [type: control]
  }
  behaviours {
    behaviour "lifecycle" {
      idle    -> running: call "start"
      running -> idle:    return "stop"
    }
  }
  style { extends: juju }
}
diagram "Topology" from "M" {
  select { nodes: idle running edges: type control }
  positions { idle left-of running gap: 120 }
}
state "Lifecycle" from "M" {
  select { behaviour: "lifecycle" }
}
"""


@pytest.fixture
def built_app(tmp_path):
    from sphinx.testing.util import SphinxTestApp

    srcdir = tmp_path / "src"
    srcdir.mkdir()
    (srcdir / "conf.py").write_text(
        'extensions = ["ggarch.sphinxcontrib_ggarch"]\n'
    )
    (srcdir / "index.rst").write_text(
        "Test\n====\n\n"
        ".. ggarch::\n"
        '   :file: model.ggarch\n'
        '   :slides: Topology | Lifecycle\n'
        '   :alt: two views\n'
    )
    (srcdir / "model.ggarch").write_text(STATE_MODEL)
    app = SphinxTestApp(
        srcdir=srcdir,
        buildername="html",
    )
    app.build()
    yield app
    app.cleanup()


class TestSlideshow:
    def test_state_view_in_slideshow(self, built_app):
        """State views render in slideshows (0.25.0).

        Before: the slideshow resolver only checked diagrams and
        sequences, so a state name fell through to "not found" and the
        slide was silently skipped.
        """
        html = (built_app.outdir / "index.html").read_text()
        assert "ggarch-slides" in html
        # Both slides present, each with its rendered image.
        assert html.count('class="ggarch-slide"') == 2
        assert html.count("<img") == 4  # light + dark per slide
        # The state view actually rendered: its SVG carries the marker id
        # defined by the state renderer.
        images = list((built_app.outdir / "_images").glob("ggarch-*.svg"))
        assert len(images) == 4
        state_svgs = [p.read_text() for p in images if "st-arrow" in p.read_text()]
        assert len(state_svgs) == 2  # light + dark state machine
        assert any("start" in svg for svg in state_svgs)


# ---------------------------------------------------------------------------
# Caption markup ({ref}`...` in :caption:) -- 2026-09-26, session 32
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    __import__("importlib").util.find_spec("myst_parser") is None,
    reason="myst_parser not installed",
)
class TestCaptionMarkup:
    def test_ref_resolves_in_caption(self, tmp_path):
        """A {ref}`...` inside :caption: renders as a resolved link.

        Before: the caption option was escaped raw text, so {ref} came
        out literally in the figcaption.
        """
        import re
        from importlib.util import find_spec

        from sphinx.testing.util import SphinxTestApp

        if find_spec("myst_parser") is None:
            pytest.skip("myst_parser not installed")
        srcdir = tmp_path / "src"
        srcdir.mkdir()
        (srcdir / "conf.py").write_text(
            'extensions = ["myst_parser", "ggarch.sphinxcontrib_ggarch"]\n'
        )
        (srcdir / "model.ggarch").write_text(STATE_MODEL)
        (srcdir / "other.md").write_text(
            "(target-label)=\n## Target\n\nBody.\n"
        )
        (srcdir / "index.md").write_text(
            "Test\n====\n\n"
            "```{ggarch}\n"
            ":file: model.ggarch\n"
            ":view: Topology\n"
            ":caption: Reads the {ref}`target-label` record.\n"
            ":alt: one view\n"
            "```\n"
        )
        app = SphinxTestApp(srcdir=srcdir, buildername="html")
        app.build()
        try:
            html = (app.outdir / "index.html").read_text()
            m = re.search(r"<figcaption>(.*?)</figcaption>", html, re.S)
            assert m, "figcaption missing"
            cap = m.group(1)
            assert 'class="reference internal"' in cap, cap
            assert "{ref}" not in cap
        finally:
            app.cleanup()
