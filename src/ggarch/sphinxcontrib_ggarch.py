"""ggarch Sphinx extension.

Registers a ``{ggarch}`` MyST/RST directive that compiles a ggarch diagram
at build time and emits a light/dark SVG pair inside a ``<figure>`` with an
optional ``<figcaption>``.

Follows the same visitor pattern as sphinxcontrib_d2.py.

Usage in MyST Markdown::

    ```{ggarch}
    :file: ../juju.ggarch
    :view: K8s deployment topology
    :caption: A live Kubernetes deployment.
    :alt: Controller pod and unit pod connected via Juju API websocket.
    ```

Slideshow (two or more views/sequences from the same file, one shown at a
time with prev/next navigation)::

    ```{ggarch}
    :file: ../principles.ggarch
    :slides: "Notify then pull | Initial event"
    :slide-captions: "Normal cycle. | On creation, the watcher fires immediately."
    :alt: Watcher notification sequence.
    ```

Options
-------
:view:            Name of the diagram view to render.
:sequence:        Name of the sequence view to render.
:slides:          Pipe-separated list of view/sequence names for a slideshow.
:slide-captions:  Pipe-separated captions matching :slides:.
:caption:         Figure caption (rendered inside the figure, survives expand).
:alt:             Required. Prose description for accessibility.
:file:            Path to a .ggarch file, relative to the source document.
:class:           Extra CSS class on the figure element.
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
        "view":           directives.unchanged,
        "sequence":       directives.unchanged,
        "slides":         directives.unchanged,   # "Name 1 | Name 2 | ..."
        "slide-captions": directives.unchanged,   # "Cap 1 | Cap 2 | ..."
        "file":           directives.unchanged,   # path relative to source doc
        "caption":        directives.unchanged,
        "alt":            directives.unchanged,
        "class":          directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        file_opt = self.options.get("file", "")
        abs_path = ""
        if file_opt:
            src_dir = os.path.dirname(self.env.docname)
            abs_path = os.path.join(self.env.srcdir, src_dir, file_opt)
            try:
                code = open(abs_path, encoding="utf-8").read()
            except OSError as exc:
                return [self.reporter.error(
                    f"ggarch: cannot read {abs_path}: {exc}", line=self.lineno
                )]
            self.env.note_dependency(abs_path)
        else:
            code = "\n".join(self.content)

        node = ggarch()
        node["code"]           = code
        node["file_path"]      = abs_path
        node["view"]           = self.options.get("view", "")
        node["sequence"]       = self.options.get("sequence", "")
        node["slides"]         = self.options.get("slides", "")
        node["slide_captions"] = self.options.get("slide-captions", "")
        node["caption"]        = self.options.get("caption", "")
        node["alt"]            = self.options.get("alt", "Architecture diagram")
        node["css_class"]      = self.options.get("class", "")
        self.set_source_info(node)
        return [node]


# ---------------------------------------------------------------------------
# SVG rendering helpers
# ---------------------------------------------------------------------------

def _render_pair(
    self: object,
    code: str,
    view_name: str = "",
    sequence_name: str = "",
    file_path: str = "",
) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
    """Compile one view/sequence to a light+dark SVG pair.

    Returns ((relfn, outfn), (relfn, outfn)) or (None, None) on error.
    """
    outdir = os.path.join(self.builder.outdir, self.builder.imagedir)
    ensuredir(outdir)

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
        seq = next((s for s in f.sequences if s.name == sequence_name), None)
        if seq is None and f.sequences:
            seq = f.sequences[0]
        if seq is None:
            logger.warning("ggarch: no sequence views in source")
            return None, None
        model = f.get_model(seq.model_name)
        results = []
        for suffix, dark in (("light", False), ("dark", True)):
            hashkey = (code + sequence_name + suffix + __version__ + mtime).encode()
            basename = f"ggarch-{hashlib.sha1(hashkey).hexdigest()}"  # noqa: S324
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

    # Diagram view
    if not f.diagrams:
        logger.warning("ggarch: no diagram views in source")
        return None, None

    if view_name:
        diagram = next((d for d in f.diagrams if d.name == view_name), None)
        if diagram is None:
            names = [d.name for d in f.diagrams]
            logger.warning(f"ggarch: view {view_name!r} not found; available: {names}")
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
        hashkey = (code + (view_name or "") + suffix + __version__ + mtime).encode()
        basename = f"ggarch-{hashlib.sha1(hashkey).hexdigest()}"  # noqa: S324
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


def _register_image(self: object, outfn: str) -> str:
    """Register an image file with the builder and return its URI."""
    self.builder.images[outfn] = os.path.basename(outfn)
    return posixpath.join(
        self.builder.imgpath,
        urllib.parse.quote(self.builder.images[outfn]),
    )


# ---------------------------------------------------------------------------
# CSS + JS
# ---------------------------------------------------------------------------

_GGARCH_CSS = """\
figure.ggarch-figure {
    margin: 1.2em auto;
    text-align: center;
}
figure.ggarch-figure figcaption {
    font-size: 0.875em;
    color: #555;
    margin-top: 0.5em;
    font-style: italic;
}
[data-theme="dark"] figure.ggarch-figure figcaption,
.dark figure.ggarch-figure figcaption {
    color: #aaa;
}
.ggarch-diagram {
    position: relative;
}
.ggarch-img {
    display: inline-block;
    max-width: 100%;
    height: auto;
}
/* Slideshow */
.ggarch-slides {
    position: relative;
}
.ggarch-slide { display: none; }
.ggarch-slide.active { display: block; }
.ggarch-slide-nav {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
    font-size: 0.8em;
    color: #666;
}
[data-theme="dark"] .ggarch-slide-nav,
.dark .ggarch-slide-nav { color: #aaa; }
.ggarch-slide-btn {
    background: none;
    border: 1px solid #ccc;
    border-radius: 3px;
    padding: 1px 8px;
    cursor: pointer;
    font-size: 0.85em;
    color: inherit;
    line-height: 1.6;
}
.ggarch-slide-btn:disabled { opacity: 0.35; cursor: default; }
.ggarch-slide-btn:not(:disabled):hover { border-color: #888; }
.ggarch-slide-counter { min-width: 2.5em; text-align: center; }
/* Expand button */
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
/* Modal */
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
.ggarch-modal-inner img { display: block; max-width: 85vw; max-height: 78vh; width: auto; height: auto; }
.ggarch-modal-caption {
    font-size: 0.85em;
    font-style: italic;
    color: #555;
    margin-top: 8px;
    max-width: 85vw;
}
[data-theme="dark"] .ggarch-modal-caption,
.dark .ggarch-modal-caption { color: #aaa; }
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

  function closeModal() {
    modal.classList.remove('active');
    var old = inner.querySelector('.ggarch-modal-img');
    if (old) inner.removeChild(old);
    var oldCap = inner.querySelector('.ggarch-modal-caption');
    if (oldCap) inner.removeChild(oldCap);
    document.body.style.overflow = '';
  }
  closeBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', function(e) { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && modal.classList.contains('active')) closeModal();
  });

  function openModal(src, alt, caption) {
    var clone = document.createElement('img');
    clone.className = 'ggarch-modal-img';
    clone.src = src; clone.alt = alt;
    inner.appendChild(clone);
    if (caption) {
      var cap = document.createElement('p');
      cap.className = 'ggarch-modal-caption';
      cap.textContent = caption;
      inner.appendChild(cap);
    }
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function getVisibleSrc(wrap) {
    var imgs = wrap.querySelectorAll('.ggarch-img');
    var src = '', alt = '';
    imgs.forEach(function(img) {
      var cs = window.getComputedStyle(img.parentElement);
      if (cs.display !== 'none') { src = img.src; alt = img.alt; }
    });
    if (!src && imgs.length) { src = imgs[0].src; alt = imgs[0].alt; }
    return { src: src, alt: alt };
  }

  // --- attach expand buttons and slideshow controls ---
  function attachControls() {
    // Expand buttons on plain diagrams
    document.querySelectorAll('.ggarch-diagram').forEach(function(wrap) {
      if (wrap.querySelector('.ggarch-expand-btn')) return;
      var figure = wrap.closest('figure.ggarch-figure');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ggarch-expand-btn';
      btn.setAttribute('aria-label', 'View diagram fullscreen');
      btn.innerHTML = EXPAND_ICON;
      btn.addEventListener('click', function() {
        var r = getVisibleSrc(wrap);
        var caption = figure ? (figure.querySelector('figcaption') || {}).textContent || '' : '';
        openModal(r.src, r.alt, caption);
      });
      wrap.appendChild(btn);
    });

    // Slideshow controls
    document.querySelectorAll('.ggarch-slides').forEach(function(slides) {
      if (slides.dataset.ggarchInit) return;
      slides.dataset.ggarchInit = '1';
      var allSlides = slides.querySelectorAll('.ggarch-slide');
      if (allSlides.length < 2) return;
      var idx = 0;

      var figure = slides.closest('figure.ggarch-figure');
      var figcap = figure ? figure.querySelector('figcaption') : null;

      // Attach expand button to the slides container
      var expandBtn = document.createElement('button');
      expandBtn.type = 'button';
      expandBtn.className = 'ggarch-expand-btn';
      expandBtn.setAttribute('aria-label', 'View diagram fullscreen');
      expandBtn.innerHTML = EXPAND_ICON;
      expandBtn.addEventListener('click', function() {
        var activeSlide = slides.querySelector('.ggarch-slide.active');
        var wrap = activeSlide || slides;
        var r = getVisibleSrc(wrap);
        var caption = figcap ? figcap.textContent : '';
        openModal(r.src, r.alt, caption);
      });
      slides.style.position = 'relative';
      slides.appendChild(expandBtn);

      // Nav bar
      var nav = document.createElement('div');
      nav.className = 'ggarch-slide-nav';
      var prevBtn = document.createElement('button');
      prevBtn.type = 'button'; prevBtn.className = 'ggarch-slide-btn';
      prevBtn.textContent = '\\u2190'; prevBtn.setAttribute('aria-label', 'Previous slide');
      var counter = document.createElement('span');
      counter.className = 'ggarch-slide-counter';
      var nextBtn = document.createElement('button');
      nextBtn.type = 'button'; nextBtn.className = 'ggarch-slide-btn';
      nextBtn.textContent = '\\u2192'; nextBtn.setAttribute('aria-label', 'Next slide');
      nav.appendChild(prevBtn); nav.appendChild(counter); nav.appendChild(nextBtn);
      slides.parentNode.insertBefore(nav, slides.nextSibling);

      function show(i) {
        allSlides.forEach(function(s) { s.classList.remove('active'); });
        allSlides[i].classList.add('active');
        counter.textContent = (i + 1) + ' / ' + allSlides.length;
        prevBtn.disabled = (i === 0);
        nextBtn.disabled = (i === allSlides.length - 1);
        // Update figcaption from data-caption on the slide
        if (figcap) {
          var cap = allSlides[i].dataset.caption || '';
          figcap.textContent = cap;
        }
      }

      prevBtn.addEventListener('click', function() { if (idx > 0) show(--idx); });
      nextBtn.addEventListener('click', function() { if (idx < allSlides.length - 1) show(++idx); });
      show(0);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attachControls);
  } else {
    attachControls();
  }
})();
"""


def _ensure_ggarch_assets(self: object) -> None:
    """Inject CSS + JS into the page body exactly once per page."""
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
# HTML visitor
# ---------------------------------------------------------------------------

def html_visit_ggarch(self: object, node: ggarch) -> None:
    code           = node["code"]
    view_name      = node.get("view", "")
    sequence_name  = node.get("sequence", "")
    slides_opt     = node.get("slides", "")
    slide_caps_opt = node.get("slide_captions", "")
    file_path      = node.get("file_path", "")
    alt            = node.get("alt", "") or "Architecture diagram"
    caption        = node.get("caption", "")
    extra_class    = node.get("css_class", "")

    figure_class = "ggarch-figure" + (f" {extra_class}" if extra_class else "")

    _ensure_ggarch_assets(self)

    # ---- Slideshow mode ------------------------------------------------
    if slides_opt:
        names   = [s.strip() for s in slides_opt.split("|")]
        captions = [s.strip() for s in slide_caps_opt.split("|")] if slide_caps_opt else []
        # Pad captions list to same length as names
        while len(captions) < len(names):
            captions.append("")

        # Detect whether the names are sequences or diagram views by parsing once
        try:
            f = parse(code)
            validate(f)
        except GgarchError as exc:
            logger.warning(f"ggarch slideshow parse error: {exc}")
            self.body.append(f'<pre class="ggarch-source">{self.encode(code)}</pre>\n')
            raise nodes.SkipNode

        seq_names  = {s.name for s in f.sequences}
        diag_names = {d.name for d in f.diagrams}

        self.body.append(f'<figure class="{figure_class}">\n')
        self.body.append('<div class="ggarch-slides">\n')

        any_ok = False
        for i, name in enumerate(names):
            is_seq = name in seq_names
            is_diag = name in diag_names
            if not is_seq and not is_diag:
                logger.warning(f"ggarch slideshow: {name!r} not found")
                continue

            light, dark = _render_pair(
                self, code,
                view_name=(name if is_diag else ""),
                sequence_name=(name if is_seq else ""),
                file_path=file_path,
            )
            if light is None and dark is None:
                continue

            cap = captions[i]
            self.body.append(f'<div class="ggarch-slide" data-caption="{self.encode(cap)}">\n')
            if light is not None:
                uri = _register_image(self, light[1])
                self.body.append(
                    f'<div class="only-light">'
                    f'<img class="ggarch-img" src="{uri}" alt="{self.encode(alt)}" style="max-width:100%; height:auto;" />'
                    f'</div>\n'
                )
            if dark is not None:
                uri = _register_image(self, dark[1])
                self.body.append(
                    f'<div class="only-dark">'
                    f'<img class="ggarch-img" src="{uri}" alt="{self.encode(alt)}" style="max-width:100%; height:auto;" />'
                    f'</div>\n'
                )
            self.body.append('</div>\n')  # .ggarch-slide
            any_ok = True

        self.body.append('</div>\n')  # .ggarch-slides

        # figcaption starts with first slide's caption; JS updates it on nav
        first_cap = captions[0] if captions else caption
        if first_cap or caption:
            self.body.append(f'<figcaption>{self.encode(first_cap or caption)}</figcaption>\n')

        self.body.append('</figure>\n')
        raise nodes.SkipNode

    # ---- Single diagram / sequence mode --------------------------------
    light, dark = _render_pair(
        self, code, view_name, sequence_name, file_path
    )

    if light is None and dark is None:
        self.body.append(f'<pre class="ggarch-source">{self.encode(code)}</pre>\n')
        raise nodes.SkipNode

    self.body.append(f'<figure class="{figure_class}">\n')
    self.body.append('<div class="ggarch-diagram">\n')

    if light is not None:
        uri = _register_image(self, light[1])
        self.body.append(
            f'<div class="only-light">'
            f'<img class="ggarch-img" src="{uri}" alt="{self.encode(alt)}" style="max-width:100%; height:auto;" />'
            f'</div>\n'
        )
    if dark is not None:
        uri = _register_image(self, dark[1])
        self.body.append(
            f'<div class="only-dark">'
            f'<img class="ggarch-img" src="{uri}" alt="{self.encode(alt)}" style="max-width:100%; height:auto;" />'
            f'</div>\n'
        )

    self.body.append('</div>\n')  # .ggarch-diagram

    if caption:
        self.body.append(f'<figcaption>{self.encode(caption)}</figcaption>\n')

    self.body.append('</figure>\n')
    raise nodes.SkipNode


# ---------------------------------------------------------------------------
# Non-HTML visitors
# ---------------------------------------------------------------------------

def markdown_visit_ggarch(self: object, node: ggarch) -> None:
    """Emit ggarch source verbatim in markdown/llms output."""
    code    = node["code"]
    alt     = node.get("alt", "")
    caption = node.get("caption", "")
    if alt:
        self.add(f"<!-- {alt} -->", prefix_eol=1, suffix_eol=1)
    self.add("```ggarch", prefix_eol=1, suffix_eol=1)
    self.add(code, prefix_eol=0, suffix_eol=1)
    self.add("```", prefix_eol=1, suffix_eol=2)
    if caption:
        self.add(f"*{caption}*", prefix_eol=1, suffix_eol=2)
    raise nodes.SkipNode


def text_visit_ggarch(self: object, node: ggarch) -> None:
    alt     = node.get("alt", "")
    caption = node.get("caption", "")
    text    = alt or "Architecture diagram"
    if caption:
        text += f": {caption}"
    self.add_text(f"[{text}]")
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
