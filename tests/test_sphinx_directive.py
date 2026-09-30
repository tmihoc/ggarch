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


def test_modal_has_dark_rules_for_pages_that_follow_the_os_theme():
    """Diagrams have a transparent canvas, so the expand modal's own
    background decides how a diagram reads. Pages in "auto" mode carry no
    explicit dark marker, so every dark rule needs a media-query twin."""
    pytest.importorskip("sphinx")
    from ggarch.sphinxcontrib_ggarch import _GGARCH_CSS

    auto = _GGARCH_CSS[_GGARCH_CSS.index("@media (prefers-color-scheme: dark)"):]
    assert 'body:not([data-theme="light"]) .ggarch-modal-inner' in auto
    assert "#1e1e2e" in auto


CAPTIONED_INDEX = (
    "Test\n====\n\n"
    ".. ggarch::\n"
    '   :file: model.ggarch\n'
    '   :slides: Topology | Lifecycle\n'
    '   :slide-captions: Zebra caption for the first slide. | Quokka caption for the second slide.\n'
    '   :alt: two views\n'
)


def _build(tmp_path, buildername, index=CAPTIONED_INDEX):
    from sphinx.testing.util import SphinxTestApp

    srcdir = tmp_path / f"src-{buildername}"
    srcdir.mkdir()
    (srcdir / "conf.py").write_text('extensions = ["ggarch.sphinxcontrib_ggarch"]\n')
    (srcdir / "index.rst").write_text(index)
    (srcdir / "model.ggarch").write_text(STATE_MODEL)
    app = SphinxTestApp(srcdir=srcdir, buildername=buildername)
    app.build()
    return app


class TestSlideshowCaptionsAreText:
    """Slide captions carry the narration, so they must exist as text.

    Before: captions lived only in data-caption attributes that JavaScript
    swapped in, every slide shared one alt, the search index saw nothing and
    the text output carried no captions.
    """

    def test_html_lists_every_caption_for_assistive_tech(self, tmp_path):
        app = _build(tmp_path, "html")
        try:
            html = (app.outdir / "index.html").read_text()
        finally:
            app.cleanup()
        assert '<ol class="ggarch-slide-captions">' in html
        assert "<strong>Topology:</strong> Zebra caption for the first slide." in html
        assert "<strong>Lifecycle:</strong> Quokka caption for the second slide." in html

    def test_html_gives_each_slide_its_own_alt(self, tmp_path):
        app = _build(tmp_path, "html")
        try:
            html = (app.outdir / "index.html").read_text()
        finally:
            app.cleanup()
        assert 'alt="Topology (slide 1 of 2)"' in html
        assert 'alt="Lifecycle (slide 2 of 2)"' in html
        # The figure-level alt labels the group instead of repeating on every image.
        assert 'role="group" aria-label="two views"' in html
        assert 'alt="two views"' not in html

    def test_search_index_finds_caption_words(self, tmp_path):
        app = _build(tmp_path, "html")
        try:
            index = (app.outdir / "searchindex.js").read_text()
        finally:
            app.cleanup()
        assert "zebra" in index
        assert "quokka" in index

    def test_text_output_carries_the_captions(self, tmp_path):
        app = _build(tmp_path, "text")
        try:
            text = " ".join((app.outdir / "index.txt").read_text().split())
        finally:
            app.cleanup()
        assert "1. Topology: Zebra caption for the first slide." in text
        assert "2. Lifecycle: Quokka caption for the second slide." in text

    def test_markdown_visitor_numbers_the_captions(self):
        from docutils import nodes
        from ggarch.sphinxcontrib_ggarch import ggarch, markdown_visit_ggarch

        node = ggarch()
        node["code"] = "model {}"
        node["slides"] = "One | Two | Three"
        node["slide_captions"] = "First. |  | Third."
        added = []

        class Fake:
            def add(self, text, prefix_eol=0, suffix_eol=0):
                added.append(text)

        try:
            markdown_visit_ggarch(Fake(), node)
        except nodes.SkipNode:
            pass
        assert "1. **One:** First." in added
        assert "2. **Three:** Third." in added  # the empty caption is dropped
