"""ggarch Sphinx extension.

Registers a ``{ggarch}`` MyST/RST directive that compiles a ggarch diagram
at build time and emits a light/dark SVG pair with a lightbox anchor.

Usage in MyST Markdown::

    ```{ggarch}
    :view: K8s deployment topology
    :alt: Controller pod and unit pod connected via Juju API websocket.
    model "..." { ... }
    diagram "..." from "..." { ... }
    ```

Or with a separate model file::

    ```{ggarch}
    :file: ../../diagrams/juju.ggarch
    :view: K8s deployment topology
    :alt: ...
    ```

Options
-------
:view:      Name of the diagram view to render (required when the source
            contains multiple views, optional when there is only one).
:alt:       Required. Prose description for agents and screen readers.
:file:      Path to a .ggarch file relative to the source document.
            When given, the directive body is ignored.
:class:     CSS class to add to the outer wrapper div.

Output
------
In HTML output: a ``<div class="ggarch-diagram">`` containing two
``<div>`` elements (one ``only-light``, one ``only-dark``), each holding
an ``<img>`` tag pointing to the generated SVG. The SVGs are written to
the Sphinx ``_images`` directory.

In markdown/llms output: the ggarch source is emitted verbatim as a
fenced ``ggarch`` code block, preceded by an HTML comment with the alt
text. This ensures agents reading the page see the full diagram source.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.application import Sphinx
from sphinx.util.docutils import SphinxDirective

from ggarch.errors import GgarchError
from ggarch.parser import parse
from ggarch.renderer import render
from ggarch.router import route
from ggarch.solver import solve
from ggarch.validator import validate


# ---------------------------------------------------------------------------
# Directive
# ---------------------------------------------------------------------------

class GgarchDirective(SphinxDirective):
    """The {ggarch} directive."""

    has_content = True
    required_arguments = 0
    optional_arguments = 0
    option_spec = {
        "view":  directives.unchanged,
        "alt":   directives.unchanged,
        "file":  directives.unchanged,
        "class": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        env = self.env
        app: Sphinx = env.app

        # --- Load source ---
        if "file" in self.options:
            src_path = Path(env.docname).parent / self.options["file"]
            src_path = Path(env.srcdir) / src_path
            try:
                source = src_path.read_text(encoding="utf-8")
            except OSError as exc:
                return [self._error(f"ggarch: cannot read {src_path}: {exc}")]
            env.note_dependency(str(src_path))
        else:
            source = "\n".join(self.content)

        if not source.strip():
            return [self._error("ggarch: empty diagram source")]

        alt = self.options.get("alt", "Architecture diagram")
        view_name = self.options.get("view", None)
        css_class = self.options.get("class", "ggarch-diagram")

        # --- Parse and validate ---
        try:
            f = parse(source)
            validate(f)
        except GgarchError as exc:
            return [self._error(f"ggarch parse/validate error: {exc}")]

        if not f.diagrams:
            return [self._error("ggarch: no diagram views in source")]

        if view_name:
            diagram = next((d for d in f.diagrams if d.name == view_name), None)
            if diagram is None:
                names = [d.name for d in f.diagrams]
                return [self._error(
                    f"ggarch: view {view_name!r} not found; "
                    f"available: {names}"
                )]
        else:
            diagram = f.diagrams[0]

        model = f.get_model(diagram.model_name)

        # --- Solve and render ---
        try:
            layout = solve(diagram, model)
            rl = route(layout, model, diagram.select)
            light_svg = render(rl, model, diagram, dark=False)
            dark_svg  = render(rl, model, diagram, dark=True)
        except GgarchError as exc:
            return [self._error(f"ggarch render error: {exc}")]

        # --- Write SVGs to _images ---
        images_dir = Path(app.outdir) / "_images"
        images_dir.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha1(source.encode()).hexdigest()[:16]
        light_name = f"ggarch-{digest}-light.svg"
        dark_name  = f"ggarch-{digest}-dark.svg"

        (images_dir / light_name).write_text(light_svg, encoding="utf-8")
        (images_dir / dark_name).write_text(dark_svg,  encoding="utf-8")

        # Relative URI from the HTML page to _images.
        light_uri = f"../../_images/{light_name}"
        dark_uri  = f"../../_images/{dark_name}"

        # --- Build docutils nodes ---
        # HTML output: light/dark pair.
        light_img = nodes.image(
            uri=light_uri, alt=alt,
        )
        light_img["classes"].append("only-light")
        dark_img = nodes.image(
            uri=dark_uri, alt=alt,
        )
        dark_img["classes"].append("only-dark")

        wrapper = nodes.container()
        wrapper["classes"].append(css_class)
        wrapper += light_img
        wrapper += dark_img

        # Markdown/llms output: emit source verbatim in a raw node.
        # HTML comment carries the alt text; fenced block carries the source.
        raw_md = (
            f"<!-- {alt} -->\n"
            f"```ggarch\n{source}\n```\n"
        )
        raw_node = nodes.raw("", raw_md, format="markdown")

        return [wrapper, raw_node]

    def _error(self, msg: str) -> nodes.system_message:
        return self.reporter.error(msg, line=self.lineno)


# ---------------------------------------------------------------------------
# Extension setup
# ---------------------------------------------------------------------------

def setup(app: Sphinx) -> dict[str, Any]:
    app.add_directive("ggarch", GgarchDirective)

    # Add CSS for light/dark switching.
    app.add_css_file("ggarch.css")

    # Write the CSS file on builder-inited if it doesn't exist.
    app.connect("builder-inited", _write_css)

    return {
        "version": "0.1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }


def _write_css(app: Sphinx) -> None:
    static_dir = Path(app.outdir) / "_static"
    static_dir.mkdir(parents=True, exist_ok=True)
    css_path = static_dir / "ggarch.css"
    if not css_path.exists():
        css_path.write_text(_CSS, encoding="utf-8")


_CSS = """\
/* ggarch diagram light/dark switching */
.ggarch-diagram { margin: 1.5em 0; }
.ggarch-diagram img { max-width: 100%; height: auto; }

/* Light mode: show light, hide dark */
@media (prefers-color-scheme: light) {
  .ggarch-diagram .only-dark  { display: none; }
}
/* Dark mode: show dark, hide light */
@media (prefers-color-scheme: dark) {
  .ggarch-diagram .only-light { display: none; }
}
/* Canonical Sphinx theme data-theme attribute override */
[data-theme="light"] .ggarch-diagram .only-dark  { display: none; }
[data-theme="dark"]  .ggarch-diagram .only-light  { display: none; }
"""
