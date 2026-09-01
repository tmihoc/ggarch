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

logger = logging.getLogger(__name__)


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
        "sequence": directives.unchanged,
        "file":     directives.unchanged,   # path to .ggarch file, relative to source doc
        "alt":      directives.unchanged,
        "class":    directives.unchanged,
    }
    def run(self) -> list[nodes.Node]:
        file_opt = self.options.get("file", "")
        if file_opt:
            # Resolve path relative to the document's source directory.
            src_dir = os.path.dirname(self.env.docname)
            abs_path = os.path.join(self.env.srcdir, src_dir, file_opt)
            try:
                code = open(abs_path, encoding="utf-8").read()
            except OSError as exc:
                return [self.reporter.error(
                    f"ggarch: cannot read {abs_path}: {exc}", line=self.lineno
                )]
            # Register as a dependency so changes trigger a rebuild.
            self.env.note_dependency(abs_path)
        else:
            code = "\n".join(self.content)
        node = ggarch()
        node["code"]      = code
        node["file_path"] = abs_path if file_opt else ""
        node["view"]      = self.options.get("view", "")
        node["sequence"]  = self.options.get("sequence", "")
        node["alt"]       = self.options.get("alt", "Architecture diagram")
        node["css_class"] = self.options.get("class", "ggarch-diagram")
        self.set_source_info(node)
        return [node]


def render_ggarch_pair(
    self: object,
    code: str,
    view_name: str,
    sequence_name: str = "",
    file_path: str = "",
    prefix: str = "ggarch",
) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
    """Compile ggarch source to light and dark SVGs.

    If sequence_name is given, renders a sequence view instead of a diagram.
    file_path, if given, is included in the cache hash so edits to the
    .ggarch file invalidate cached SVGs automatically.
    Returns ((relfn, outfn), (relfn, outfn)) — same shape as D2.
    """
    outdir = os.path.join(self.builder.outdir, self.builder.imagedir)
    ensuredir(outdir)

    # Include file mtime in hash so edits invalidate the cache.
    mtime = ""
    if file_path and os.path.isfile(file_path):
        mtime = str(os.path.getmtime(file_path))

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
            hashkey = (code + sequence_name + suffix + __version__ + mtime).encode("utf-8")
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
        hashkey = (code + (view_name or "") + suffix + __version__ + mtime).encode("utf-8")
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
    theme_class: str,
) -> None:
    """Emit an <img> inside a theme-class wrapper div. No lightbox anchor."""
    self.builder.images[outfn] = os.path.basename(outfn)
    uri = posixpath.join(
        self.builder.imgpath,
        urllib.parse.quote(self.builder.images[outfn]),
    )
    self.body.append(
        f'<div class="{theme_class}">'
        f'<img class="ggarch-img" src="{uri}" alt="{alt}" style="width:100%;" />'
        f'</div>\n'
    )


# ---------------------------------------------------------------------------
# Per-page asset injection (CSS + JS, emitted once per page)
# ---------------------------------------------------------------------------

_GGARCH_CSS = """\
.ggarch-diagram {
    position: relative;
}
.ggarch-expand-btn {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 28px;
    height: 28px;
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid rgba(0, 0, 0, 0.25);
    border-radius: 4px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    opacity: 0.55;
    transition: opacity 0.15s, box-shadow 0.15s;
    box-shadow: 0 1px 4px rgba(0,0,0,0.15);
    z-index: 10;
}
.ggarch-expand-btn:hover { opacity: 1; box-shadow: 0 2px 8px rgba(0,0,0,0.25); }
[data-theme="dark"] .ggarch-expand-btn,
.dark .ggarch-expand-btn {
    background: rgba(40, 40, 40, 0.92);
    border-color: rgba(255,255,255,0.2);
    color: #eee;
}
.ggarch-modal {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.75);
    z-index: 9999;
    align-items: center;
    justify-content: center;
}
.ggarch-modal.active { display: flex; }
.ggarch-modal-inner {
    position: relative;
    background: #fff;
    border-radius: 6px;
    padding: 12px;
    max-width: 92vw;
    max-height: 92vh;
    overflow: auto;
    box-shadow: 0 8px 40px rgba(0,0,0,0.4);
}
[data-theme="dark"] .ggarch-modal-inner,
.dark .ggarch-modal-inner { background: #1e1e2e; }
.ggarch-modal-inner img { display: block; max-width: 85vw; max-height: 82vh; width: auto; height: auto; }
.ggarch-close-btn {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 28px;
    height: 28px;
    background: rgba(255,255,255,0.92);
    border: 1px solid rgba(0,0,0,0.25);
    border-radius: 4px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    z-index: 10000;
    box-shadow: 0 1px 4px rgba(0,0,0,0.15);
}
.ggarch-close-btn:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.25); }
[data-theme="dark"] .ggarch-close-btn,
.dark .ggarch-close-btn { background: rgba(40,40,40,0.92); border-color: rgba(255,255,255,0.2); color: #eee; }
"""

_GGARCH_JS = """\
(function () {
  if (window._ggarchAssetsAttached) return;
  window._ggarchAssetsAttached = true;

  var EXPAND_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9,1 13,1 13,5"/><polyline points="5,13 1,13 1,9"/><polyline points="13,1 8,6"/><polyline points="1,13 6,8"/></svg>';
  var CLOSE_ICON  = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><line x1="1" y1="1" x2="11" y2="11"/><line x1="11" y1="1" x2="1" y2="11"/></svg>';

  // --- modal singleton ---
  var modal = document.createElement('div');
  modal.className = 'ggarch-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Diagram fullscreen view');
  var inner = document.createElement('div');
  inner.className = 'ggarch-modal-inner';
  var closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'ggarch-close-btn';
  closeBtn.setAttribute('aria-label', 'Close');
  closeBtn.innerHTML = CLOSE_ICON;
  inner.appendChild(closeBtn);
  modal.appendChild(inner);
  document.body.appendChild(modal);

  function close() {
    modal.classList.remove('active');
    var old = inner.querySelector('.ggarch-modal-img');
    if (old) inner.removeChild(old);
    document.body.style.overflow = '';
  }
  closeBtn.addEventListener('click', close);
  modal.addEventListener('click', function(e) { if (e.target === modal) close(); });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && modal.classList.contains('active')) close();
  });

  // --- attach expand buttons ---
  function attachButtons() {
    document.querySelectorAll('.ggarch-diagram').forEach(function(wrap) {
      if (wrap.querySelector('.ggarch-expand-btn')) return; // idempotent
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ggarch-expand-btn';
      btn.setAttribute('aria-label', 'View diagram fullscreen');
      btn.innerHTML = EXPAND_ICON;
      btn.addEventListener('click', function() {
        var imgs = wrap.querySelectorAll('.ggarch-img');
        var src = '', alt = '';
        imgs.forEach(function(img) {
          var cs = window.getComputedStyle(img.parentElement);
          if (cs.display !== 'none') { src = img.src; alt = img.alt; }
        });
        if (!src && imgs.length) { src = imgs[0].src; alt = imgs[0].alt; }
        var clone = document.createElement('img');
        clone.className = 'ggarch-modal-img';
        clone.src = src;
        clone.alt = alt;
        inner.appendChild(clone);
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
      });
      wrap.appendChild(btn);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attachButtons);
  } else {
    attachButtons();
  }
})();
"""


def _ensure_ggarch_assets(self: object) -> None:
    """Inject CSS + JS into the page body exactly once."""
    pages = getattr(self.builder, "_ggarch_assets_pages", None)
    if pages is None:
        self.builder._ggarch_assets_pages = set()
        pages = self.builder._ggarch_assets_pages
    key = getattr(self, "docname", id(self))
    if key in pages:
        return
    pages.add(key)
    self.body.append(f'<style>{_GGARCH_CSS}</style>\n')
    self.body.append(f'<script>{_GGARCH_JS}</script>\n')


# ---------------------------------------------------------------------------
# Visitors
# ---------------------------------------------------------------------------

def html_visit_ggarch(self: object, node: ggarch) -> None:
    code          = node["code"]
    view_name     = node.get("view", "")
    sequence_name = node.get("sequence", "")
    file_path     = node.get("file_path", "")
    alt           = node.get("alt", "") or "Architecture diagram"
    css_class     = node.get("css_class", "ggarch-diagram")

    light, dark = render_ggarch_pair(
        self, code, view_name, sequence_name, file_path
    )

    if light is None and dark is None:
        self.body.append(
            f'<pre class="ggarch-source">{self.encode(code)}</pre>\n'
        )
        raise nodes.SkipNode

    _ensure_ggarch_assets(self)

    self.body.append(f'<div class="{css_class}">\n')
    if light is not None:
        _emit_image(self, light[0], light[1], alt, "only-light")
    if dark is not None:
        _emit_image(self, dark[0], dark[1], alt, "only-dark")
    self.body.append('</div>\n')

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
