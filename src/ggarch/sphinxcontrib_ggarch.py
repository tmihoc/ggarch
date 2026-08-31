"""ggarch Sphinx extension.

Registers a ``{ggarch}`` MyST/RST directive that compiles a ggarch diagram
at build time and emits a light/dark SVG pair with lightbox anchors.

Follows the same visitor pattern as sphinxcontrib_d2.py.

Usage in MyST Markdown::

    ```{ggarch}
    :view: K8s deployment topology
    :alt: Controller pod and unit pod connected via Juju API websocket.
    model "..." { ... }
    diagram "..." from "..." { ... }
    ```

-------
:view:   Name of the diagram view to render (optional if only one view).
:alt:    Required. Prose description for agents and screen readers.
:class:  CSS class added to each image wrapper div (default: ggarch-diagram).
"""
from __future__ import annotations

import hashlib
import os
import posixpath
import urllib.parse
from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective
from sphinx.util.osutil import ensuredir

from ggarch.errors import GgarchError
from ggarch.parser import parse
from ggarch.renderer import render
from ggarch.router import route
from ggarch.solver import solve
from ggarch.validator import validate
from ggarch.sequence_renderer import render_sequence
from ggarch import __version__


# ---------------------------------------------------------------------------
# Custom node
# ---------------------------------------------------------------------------

class ggarch(nodes.General, nodes.Inline, nodes.Element):
    pass


# ---------------------------------------------------------------------------
# Directive
# ---------------------------------------------------------------------------

class GgarchDirective(SphinxDirective):
    """The {ggarch} directive."""

    has_content = True
    required_arguments = 0
    optional_arguments = 0
    option_spec = {
        "view":     directives.unchanged,
        "sequence": directives.unchanged,  # sequence view name
        "alt":      directives.unchanged,
        "class":    directives.unchanged,
    }
    def run(self) -> list[nodes.Node]:
        code = "\n".join(self.content)
        node = ggarch()
        node["code"] = code
        node["view"] = self.options.get("view", "")
        node["sequence"] = self.options.get("sequence", "")
        node["alt"]  = self.options.get("alt", "Architecture diagram")
        node["css_class"] = self.options.get("class", "ggarch-diagram")
        self.set_source_info(node)
        return [node]


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def render_ggarch_pair(
    self: object,
    code: str,
    view_name: str,
    sequence_name: str = "",
    prefix: str = "ggarch",
) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
    """Compile ggarch source to light and dark SVGs.

    If sequence_name is given, renders a sequence view instead of a diagram.
    Returns ((relfn, outfn), (relfn, outfn)) — same shape as D2.
    """
    outdir = os.path.join(self.builder.outdir, self.builder.imagedir)
    ensuredir(outdir)

    try:
        f = parse(code)
        validate(f)
    except GgarchError as exc:
        logger.warning(f"ggarch parse/validate error: {exc}")
        return None, None

    if sequence_name:
        # --- Sequence view ---
        seq = next((s for s in f.sequences if s.name == sequence_name), None)
        if seq is None and f.sequences:
            seq = f.sequences[0]
        if seq is None:
            logger.warning(f"ggarch: no sequence views in source")
            return None, None
        model = f.get_model(seq.model_name)
        results = []
        for suffix, dark in (("light", False), ("dark", True)):
            hashkey = (code + sequence_name + suffix + __version__).encode("utf-8")
            basename = f"{prefix}-{hashlib.sha1(hashkey).hexdigest()}"  # noqa: S324
            fname = f"{basename}.svg"
            relfn = posixpath.join(self.builder.imgpath, fname)
            outfn = os.path.join(outdir, fname)
            if not os.path.isfile(outfn):
                try:
                    svg = render_sequence(seq, model, dark=dark)
                    with open(outfn, "w", encoding="utf-8") as fh:
                        fh.write(svg)
                except Exception as exc:
                    logger.warning(f"ggarch sequence render error ({suffix}): {exc}")
                    results.append(None)
                    continue
            results.append((relfn, outfn))
        return tuple(results)  # type: ignore[return-value]

    # --- Diagram view ---
    if not f.diagrams:
        logger.warning("ggarch: no diagram views in source")
        return None, None

    if view_name:
        diagram = next((d for d in f.diagrams if d.name == view_name), None)
        if diagram is None:
            names = [d.name for d in f.diagrams]
            logger.warning(
                f"ggarch: view {view_name!r} not found; available: {names}"
            )
            return None, None
    else:
        diagram = f.diagrams[0]

    model = f.get_model(diagram.model_name)

    try:
        layout = solve(diagram, model)
        rl = route(layout, model, diagram.select)
    except GgarchError as exc:
        logger.warning(f"ggarch solver/router error: {exc}")
        return None, None

    results = []
    for suffix, dark in (("light", False), ("dark", True)):
        hashkey = (code + (view_name or "") + suffix + __version__).encode("utf-8")
        basename = f"{prefix}-{hashlib.sha1(hashkey).hexdigest()}"  # noqa: S324
        fname = f"{basename}.svg"
        relfn = posixpath.join(self.builder.imgpath, fname)
        outfn = os.path.join(outdir, fname)
        if not os.path.isfile(outfn):
            try:
                svg = render(rl, model, diagram, dark=dark)
                with open(outfn, "w", encoding="utf-8") as fh:
                    fh.write(svg)
            except GgarchError as exc:
                logger.warning(f"ggarch render error ({suffix}): {exc}")
                results.append(None)
                continue
        results.append((relfn, outfn))

    return tuple(results)  # type: ignore[return-value]

def _emit_image(
    self: object,
    relfn: str,
    outfn: str,
    alt: str,
    css_class: str,
    lightbox_group: str,
) -> None:
    """Emit a lightbox-wrapped <img> inside a light/dark div."""
    self.builder.images[outfn] = os.path.basename(outfn)
    uri = posixpath.join(
        self.builder.imgpath,
        urllib.parse.quote(self.builder.images[outfn]),
    )
    self.body.append(
        f'<div class="{css_class}">'
        f'<a href="{uri}" data-lightbox="{lightbox_group}">'
        f'<img src="{uri}" alt="{alt}" style="width:100%;" />'
        f'</a>'
        f'</div>\n'
    )


# ---------------------------------------------------------------------------
# Visitors
# ---------------------------------------------------------------------------

def html_visit_ggarch(self: object, node: ggarch) -> None:
    code          = node["code"]
    view_name     = node.get("view", "")
    sequence_name = node.get("sequence", "")
    alt           = node.get("alt", "") or "Architecture diagram"
    css_class     = node.get("css_class", "ggarch-diagram")

    light, dark = render_ggarch_pair(self, code, view_name, sequence_name)

    if light is None and dark is None:
        self.body.append(
            f'<pre class="ggarch-source">{self.encode(code)}</pre>\n'
        )
        raise nodes.SkipNode

    group = "ggarch-" + hashlib.sha1(code.encode()).hexdigest()[:8]  # noqa: S324

    if light is not None:
        _emit_image(self, light[0], light[1], alt,
                    "only-light", group + "-light")
    if dark is not None:
        _emit_image(self, dark[0], dark[1], alt,
                    "only-dark", group + "-dark")

    raise nodes.SkipNode


def markdown_visit_ggarch(self: object, node: ggarch) -> None:
    """Emit ggarch source verbatim in markdown/llms output."""
    code = node["code"]
    alt  = node.get("alt", "")
    if alt:
        self.add(f"<!-- {alt} -->", prefix_eol=1, suffix_eol=1)
    self.add("```ggarch", prefix_eol=1, suffix_eol=1)
    self.add(code, prefix_eol=0, suffix_eol=1)
    self.add("```", prefix_eol=1, suffix_eol=2)
    raise nodes.SkipNode


def text_visit_ggarch(self: object, node: ggarch) -> None:
    alt = node.get("alt", "")
    self.add_text(f"[Architecture diagram{': ' + alt if alt else ''}]")
    raise nodes.SkipNode


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup(app: object) -> dict[str, Any]:
    app.add_node(
        ggarch,
        html=(html_visit_ggarch, None),
        markdown=(markdown_visit_ggarch, None),
        text=(text_visit_ggarch, None),
        man=(text_visit_ggarch, None),
    )
    app.add_directive("ggarch", GgarchDirective)
    return {
        "version": "0.1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
