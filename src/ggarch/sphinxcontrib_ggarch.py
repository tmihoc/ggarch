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
    :caption: How the watcher cycle works.
    :slide-captions: "Normal cycle. | On creation, the watcher fires immediately."
    :alt: Watcher notification sequence.
    ```

In slideshow mode, ``:caption:`` is a static label rendered above the carousel
(it frames the whole slideshow and does not change on navigation).
``:slide-captions:`` supplies the per-slide text that updates in the figcaption
as the reader navigates. Both are optional independently.

Options
-------
:view:            Name of any view to render -- diagram, sequence, or
                  state machine. Searches diagrams first, then
                  sequences, then states.
:sequence:        Alias for :view:; kept for backwards compatibility.
:slides:          Pipe-separated list of view/sequence/state names for a slideshow.
:slide-captions:  Pipe-separated captions matching :slides:; updated on nav.
:caption:         Single diagram: figure caption. Slideshow: static label
                  above the carousel, does not change on navigation.
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
from docutils.statemachine import StringList
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective
from sphinx.util.osutil import ensuredir

from ggarch.errors import GgarchError
from ggarch.model import AnnotationLegend
from ggarch.parser import parse
from ggarch.renderer import render, _legend_items
from ggarch.router import route
from ggarch.solver import solve
from ggarch.validator import validate
from ggarch.sequence_renderer import render_sequence
from ggarch.state_renderer import render_state
from ggarch.presets import get_preset, resolve_edge_style, resolve_style
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
        "no-legend":      directives.flag,        # suppress HTML legend strip
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
        node["no_legend"]      = "no-legend" in self.options
        self.set_source_info(node)

        # A caption may carry MyST markup ({ref}`...` etc.). The raw string
        # stays on the node for the text/llms visitors; when markup is
        # present, a parsed copy is attached as a child node so the HTML
        # writer can emit resolved references inside the figcaption.
        caption = node["caption"]
        if caption and "{" in caption:
            try:
                container = nodes.container(classes=["ggarch-caption-content"])
                self.state.nested_parse(
                    StringList(caption.splitlines(),
                               source=self.state.document["source"]),
                    0, container,
                )
                node += container
                node["caption_markup"] = True
            except Exception:  # fall back to the plain-text caption
                logger.warning(f"ggarch: could not parse caption markup: {caption!r}",
                               location=node)
        return [node]


# ---------------------------------------------------------------------------
# SVG rendering helpers
# ---------------------------------------------------------------------------
_SOURCE_TOKEN: str | None = None


def _source_cache_token(pkg_dir: str | None = None) -> str:
    """Content hash of ggarch's own source files.

    The SVG cache key covers the .ggarch code, view name, mtime and
    __version__, but none of those change when ggarch's Python source is
    edited -- the known "stale SVGs after renderer changes without a
    version bump" issue. This token closes that gap: any edit to a module
    in the package changes the token, hence the cache key.

    Computed once per process for the real package dir (editable installs
    point at the source tree). An explicit pkg_dir bypasses the cache,
    which keeps the function testable.
    """
    global _SOURCE_TOKEN
    if pkg_dir is None:
        if _SOURCE_TOKEN is not None:
            return _SOURCE_TOKEN
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha1()
    for fn in sorted(os.listdir(pkg_dir)):
        if fn.endswith(".py"):
            with open(os.path.join(pkg_dir, fn), "rb") as fh:
                h.update(fn.encode())
                h.update(fh.read())
    token = h.hexdigest()
    if _SOURCE_TOKEN is None and pkg_dir == os.path.dirname(os.path.abspath(__file__)):
        _SOURCE_TOKEN = token
    return token


def _cache_basename(
    code: str, name_key: str, suffix: str, mtime: str, extra: str = ""
) -> str:
    """Cache-file basename for one rendered SVG.

    Key inputs: .ggarch code, view/sequence name, light/dark suffix,
    source mtime, per-site extras (e.g. skip_legend) -- plus the ggarch
    source token, so renderer edits invalidate the cache even without a
    __version__ bump.
    """
    hashkey = (code + name_key + suffix + __version__ + mtime + extra
               + _source_cache_token()).encode()
    return f"ggarch-{hashlib.sha1(hashkey).hexdigest()}"  # noqa: S324


def _render_pair(
    self: object,
    code: str,
    view_name: str = "",
    sequence_name: str = "",
    file_path: str = "",
    skip_legend: bool = False,
) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
    """Compile one view/sequence to a light+dark SVG pair.

    view_name is tried against diagrams first, then sequences, then
    states. sequence_name is kept for backwards compatibility.

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

    # Resolve the name: explicit sequence_name wins; otherwise try view_name
    # against diagrams first, then sequences, then states.
    resolved_sequence = None
    resolved_diagram  = None
    resolved_state    = None

    if sequence_name:
        resolved_sequence = next((s for s in f.sequences if s.name == sequence_name), None)
        if resolved_sequence is None:
            logger.warning(f"ggarch: sequence {sequence_name!r} not found")
            return None, None
    elif view_name:
        resolved_diagram = next((d for d in f.diagrams if d.name == view_name), None)
        if resolved_diagram is None:
            resolved_sequence = next((s for s in f.sequences if s.name == view_name), None)
        if resolved_diagram is None and resolved_sequence is None:
            resolved_state = next((st for st in f.states if st.name == view_name), None)
        if resolved_diagram is None and resolved_sequence is None and resolved_state is None:
            avail = ([d.name for d in f.diagrams]
                     + [s.name for s in f.sequences]
                     + [st.name for st in f.states])
            logger.warning(f"ggarch: view {view_name!r} not found; available: {avail}")
            return None, None
    else:
        # No name given: fall back to first diagram, then first sequence,
        # then first state view.
        if f.diagrams:
            resolved_diagram = f.diagrams[0]
        elif f.sequences:
            resolved_sequence = f.sequences[0]
        elif f.states:
            resolved_state = f.states[0]
        else:
            logger.warning("ggarch: no views in source")
            return None, None

    if resolved_state is not None:
        st = resolved_state
        name_key = view_name or st.name
        model = f.get_model(st.model_name)
        results = []
        for suffix, dark in (("light", False), ("dark", True)):
            basename = _cache_basename(code, name_key, suffix, mtime)
            fname = f"{basename}.svg"
            relfn = posixpath.join(self.builder.imgpath, fname)
            outfn = os.path.join(outdir, fname)
            if not os.path.isfile(outfn):
                try:
                    svg = render_state(st, model, dark=dark)
                    with open(outfn, "w", encoding="utf-8") as fh:
                        fh.write(svg)
                except Exception as exc:
                    logger.warning(f"ggarch state render error ({suffix}): {exc}")
                    results.append(None)
                    continue
            results.append((relfn, outfn))
        return tuple(results)  # type: ignore[return-value]

    if resolved_sequence is not None:
        seq = resolved_sequence
        name_key = sequence_name or view_name
        model = f.get_model(seq.model_name)
        results = []
        for suffix, dark in (("light", False), ("dark", True)):
            basename = _cache_basename(code, name_key, suffix, mtime)
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
    diagram = resolved_diagram
    model = f.get_model(diagram.model_name)
    try:
        layout = solve(diagram, model)
        rl = route(layout, model, diagram.select)
    except GgarchError as exc:
        logger.warning(f"ggarch solver/router error: {exc}")
        return None, None

    results = []
    for suffix, dark in (("light", False), ("dark", True)):
        basename = _cache_basename(code, (view_name or ""), suffix, mtime,
                                   ("L" if skip_legend else ""))
        fname = f"{basename}.svg"
        relfn = posixpath.join(self.builder.imgpath, fname)
        outfn = os.path.join(outdir, fname)
        if not os.path.isfile(outfn):
            try:
                svg = render(rl, model, diagram, dark=dark, skip_legend=skip_legend)
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
/* Inline HTML legend strip */
.ggarch-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.15em 1.2em;
    justify-content: center;
    font-size: 0.78em;
    color: #555;
    margin: 0.5em auto 0;
    max-width: 100%;
    line-height: 1.8;
}
[data-theme="dark"] .ggarch-legend,
.dark .ggarch-legend { color: #aaa; }
.ggarch-legend-item {
    display: inline-flex;
    align-items: center;
    gap: 0.35em;
    white-space: nowrap;
}
.ggarch-legend-swatch {
    display: inline-block;
    width: 20px;
    height: 12px;
    border-radius: 2px;
    flex-shrink: 0;
    vertical-align: middle;
}
.ggarch-legend-line {
    display: inline-block;
    width: 28px;
    height: 12px;
    flex-shrink: 0;
    vertical-align: middle;
}
[data-theme="dark"] .ggarch-legend-swatch { opacity: 0.85; }
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
.ggarch-slides-caption {
    font-size: 0.9em;
    font-weight: 600;
    margin-bottom: 6px;
    color: inherit;
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
    color: #444;
    opacity: 0.65;
    transition: opacity 0.15s, box-shadow 0.15s;
    box-shadow: 0 1px 4px rgba(0,0,0,0.15);
    z-index: 10;
}
.ggarch-expand-btn:hover { opacity: 1; box-shadow: 0 2px 8px rgba(0,0,0,0.25); }
[data-theme="dark"] .ggarch-expand-btn,
.dark .ggarch-expand-btn {
    background: rgba(40, 40, 40, 0.92);
    border-color: rgba(255,255,255,0.2);
    color: #ddd;
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
.ggarch-modal-inner img { display: block; width: 100%; max-width: 85vw; max-height: 78vh; object-fit: contain; }
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
    color: #444;
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
    ['ggarch-modal-img', 'ggarch-modal-legend', 'ggarch-modal-caption'].forEach(function(cls) {
      var el = inner.querySelector('.' + cls);
      if (el) inner.removeChild(el);
    });
    document.documentElement.style.overflow = '';
    document.body.style.overflow = '';
    if (openModal._scrollY != null) {
      window.scrollTo(0, openModal._scrollY);
      openModal._scrollY = null;
    }
  }
  closeBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', function(e) { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && modal.classList.contains('active')) closeModal();
  });

  function openModal(src, alt, legendEl, caption) {
    var clone = document.createElement('img');
    clone.className = 'ggarch-modal-img';
    clone.src = src; clone.alt = alt;
    inner.appendChild(clone);
    if (legendEl) {
      var legClone = legendEl.cloneNode(true);
      legClone.className = 'ggarch-legend ggarch-modal-legend';
      inner.appendChild(legClone);
    }
    if (caption) {
      var cap = document.createElement('p');
      cap.className = 'ggarch-modal-caption';
      cap.textContent = caption;
      inner.appendChild(cap);
    }
    modal.classList.add('active');
    // Remember the scroll position: hiding the body overflow reflows
    // the page and some themes lose the offset — closing then jumped
    // the reader to the top of the document (review round 2).
    openModal._scrollY = window.scrollY;
    document.documentElement.style.overflow = 'hidden';
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
        var legendEl = figure ? figure.querySelector('.ggarch-legend') : null;
        openModal(r.src, r.alt, legendEl, caption);
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
        openModal(r.src, r.alt, null, caption);
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
# Legend HTML extraction
# ---------------------------------------------------------------------------

# Legend swatches resolve from the model's style block (merged onto the
# preset) so custom node and edge types style correctly. Light mode only:
# the HTML legend strip renders once, on the light page background.

def _swatch(style) -> tuple[str, str]:
    """(fill, stroke) for a resolved NodeStyle, with sensible defaults."""
    if style is None:
        return "#FFFFFF", "#AAAAAA"
    return style.fill, style.stroke



def _extract_legend_html(
    code: str,
    view_name: str,
    encode,  # self.encode from the visitor
) -> str:
    """Return an HTML legend strip for the view, or '' if no legend annotation."""
    try:
        f = parse(code)
    except GgarchError:
        return ""

    diagram = next((d for d in f.diagrams if d.name == view_name), None)
    if diagram is None and f.diagrams:
        diagram = f.diagrams[0]
    if diagram is None:
        return ""

    leg = next((a for a in diagram.annotations if isinstance(a, AnnotationLegend)), None)
    if leg is None:
        return ""

    # Resolve which types are actually used — requires layout solve.
    model = f.get_model(diagram.model_name)
    try:
        layout = solve(diagram, model)
        rl = route(layout, model, diagram.select)
    except GgarchError:
        return ""
    node_styles = resolve_style(model.style)
    edge_styles = resolve_edge_style(model.style)
    node_types, edge_types = _legend_items(layout, rl.edges)

    items_html: list[str] = []

    for ntype in node_types:
        label = leg.labels.get(ntype, ntype)
        fill, stroke = _swatch(node_styles.get(ntype))
        swatch = (
            f'<span class="ggarch-legend-swatch" '
            f'style="background:{fill}; border:1.5px solid {stroke};"></span>'
        )
        items_html.append(
            f'<span class="ggarch-legend-item">{swatch} {encode(label)}</span>'
        )

    for etype in edge_types:
        label  = leg.labels.get(etype, etype)
        es = edge_styles.get(etype, edge_styles.get("default"))
        stroke, dash, width = es.stroke, es.stroke_dash, es.stroke_width
        # SVG line sample — inline, 28×12px viewBox. The head glyph
        # mirrors the renderer's arrowhead channel (ADR-004): filled
        # (committed), open (fire-and-forget V), hollow (generalization
        # triangle, background-filled), none (bare line).
        ah = 4  # arrowhead half-height
        if es.arrowhead == "open":
            head = (f'<polyline points="24 {6-ah} 28 6 24 {6+ah}" '
                    f'fill="none" stroke="{stroke}" stroke-width="1.5"/>')
        elif es.arrowhead == "hollow":
            head = (f'<polygon points="24 {6-ah} 28 6 24 {6+ah}" '
                    f'fill="none" stroke="{stroke}" '
                    f'stroke-width="1.5"/>')
        elif es.arrowhead == "none":
            head = ""
        else:
            head = (f'<polyline points="24 {6-ah} 28 6 24 {6+ah}" '
                    f'fill="{stroke}" stroke="none"/>')
        arrow = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="28" height="12" '
            f'viewBox="0 0 28 12" class="ggarch-legend-line" style="overflow:visible">'
            f'<line x1="0" y1="6" x2="24" y2="6" '
            f'stroke="{stroke}" stroke-width="{width or 1.5}"'
            + (f' stroke-dasharray="{dash}"' if dash else "")
            + f'/>'
            + head
            + f'</svg>'
        )
        items_html.append(
            f'<span class="ggarch-legend-item">{arrow} {encode(label)}</span>'
        )

    if not items_html:
        return ""

    return '<div class="ggarch-legend">' + "".join(items_html) + "</div>\n"


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
    no_legend      = node.get("no_legend", False)

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

        seq_names   = {s.name for s in f.sequences}
        diag_names  = {d.name for d in f.diagrams}
        state_names = {st.name for st in f.states}

        self.body.append(f'<figure class="{figure_class}">\n')
        if caption:
            self.body.append(f'<p class="ggarch-slides-caption">{self.encode(caption)}</p>\n')
        self.body.append('<div class="ggarch-slides">\n')

        any_ok = False
        for i, name in enumerate(names):
            is_seq   = name in seq_names
            is_diag  = name in diag_names
            is_state = name in state_names
            if not is_seq and not is_diag and not is_state:
                logger.warning(f"ggarch slideshow: {name!r} not found")
                continue

            # _render_pair resolves :view: names against diagrams, then
            # sequences, then states -- so diagrams and states both go
            # through view_name.
            light, dark = _render_pair(
                self, code,
                view_name=(name if (is_diag or is_state) else ""),
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

        # figcaption shows the first slide-caption and is updated by JS on nav.
        # :caption: is already rendered as a static label above; don't repeat it.
        first_slide_cap = captions[0] if captions else ""
        if first_slide_cap:
            self.body.append(f'<figcaption>{self.encode(first_slide_cap)}</figcaption>\n')

        self.body.append('</figure>\n')
        raise nodes.SkipNode

    # ---- Single diagram / sequence mode --------------------------------
    # Determine whether this resolves to a diagram (gets HTML legend strip)
    # or a sequence (no legend). :view: can now resolve to either type.
    try:
        _f = parse(code); validate(_f)
        _name = view_name or sequence_name
        _is_seq = bool(sequence_name) or (
            view_name
            and not any(d.name == view_name for d in _f.diagrams)
            and any(s.name == view_name for s in _f.sequences)
        )
    except Exception:
        _is_seq = bool(sequence_name)
    is_diagram = not _is_seq
    light, dark = _render_pair(
        self, code, view_name, sequence_name, file_path,
        skip_legend=is_diagram,
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

    if is_diagram and not no_legend:
        legend_html = _extract_legend_html(code, view_name, self.encode)
        if legend_html:
            self.body.append(legend_html)

    if node.get("caption_markup"):
        # Leave the figure open: the parsed caption container is a child
        # node, rendered next by the translator, and the depart visitor
        # closes both the figcaption and the figure.
        self.body.append('<figcaption>\n')
        return

    if caption:
        self.body.append(f'<figcaption>{self.encode(caption)}</figcaption>\n')

    self.body.append('</figure>\n')
    raise nodes.SkipNode


def html_depart_ggarch(self: object, node: ggarch) -> None:
    self.body.append('</figcaption>\n</figure>\n')


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
        html=(html_visit_ggarch, html_depart_ggarch),
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
