#!/usr/bin/env python3
"""Render all ggarch build artefacts.

Produces two sets of output:

  examples/<name>-light.svg / <name>-dark.svg
    Re-rendered from every .ggarch file under examples/.
    Replaces examples/render-examples.py.

  assets/<name>-light.svg / <name>-dark.svg
    Selected views from the Juju architecture docs
    (docs/juju.ggarch and docs/principles.ggarch in the juju repo,
    or whichever path is given via --juju-docs).

  assets/ggarch-demo.gif, assets/ggarch-demo-dark.gif
    Six-slide README walkthrough built from the juju.ggarch model:
    the source, three rendered narrative views, the Markdown
    directives, and the rendered Sphinx slideshow -- in light and
    dark variants.
    Requires cairosvg and ImageMagick (convert).

Run from the ggarch repo root:

    python scripts/render-assets.py                         # examples only
    python scripts/render-assets.py --juju-docs ~/git/juju/docs
    python scripts/render-assets.py --juju-docs ~/git/juju/docs --gif

Options:
    --juju-docs PATH   Path to the juju docs directory containing
                       juju.ggarch and principles.ggarch.
    --gif              Also produce assets/ggarch-demo.gif (requires
                       cairosvg and ImageMagick).
    --no-examples      Skip re-rendering examples/.
"""
from __future__ import annotations

import argparse
import base64
import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ggarch import parse, validate, solve, route, render
from ggarch.errors import ParseError
from ggarch.geometry import LABEL_FONT_SIZE
from ggarch.sequence_renderer import render_sequence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace("/", "-")


def render_pair(f, view_name: str, out_dir: pathlib.Path, stem: str) -> None:
    """Render a diagram or sequence view to light+dark SVG pair."""
    diag = next((d for d in f.diagrams if d.name == view_name), None)
    seq  = next((s for s in f.sequences if s.name == view_name), None)

    if diag is not None:
        m  = f.get_model(diag.model_name)
        rl = route(solve(diag, m), m, diag.select)
        for suffix, dark in (("light", False), ("dark", True)):
            svg = render(rl, m, diag, dark=dark, skip_legend=True)
            (out_dir / f"{stem}-{suffix}.svg").write_text(svg, encoding="utf-8")
    elif seq is not None:
        m = f.get_model(seq.model_name)
        for suffix, dark in (("light", False), ("dark", True)):
            svg = render_sequence(seq, m, dark=dark)
            (out_dir / f"{stem}-{suffix}.svg").write_text(svg, encoding="utf-8")
    else:
        raise ValueError(f"view {view_name!r} not found")

    print(f"  {stem}-light.svg  {stem}-dark.svg")


# ---------------------------------------------------------------------------
# Re-render examples/
# ---------------------------------------------------------------------------

def render_examples() -> None:
    examples_dir = ROOT / "examples"
    sources = sorted(examples_dir.glob("*.ggarch"))
    if not sources:
        print("No .ggarch files found in examples/")
        return

    total = 0
    errors = 0
    for src in sources:
        try:
            code = src.read_text(encoding="utf-8")
            f = parse(code)
            validate(f)

            views = list(f.diagrams) + list(f.sequences)
            use_index = len(views) > 1
            idx = 0

            for d in f.diagrams:
                m  = f.get_model(d.model_name)
                rl = route(solve(d, m), m, d.select)
                prefix = f"{src.stem}-{idx}" if use_index else src.stem
                for suffix, dark in (("light", False), ("dark", True)):
                    svg = render(rl, m, d, dark=dark)
                    out = src.with_name(f"{prefix}-{suffix}.svg")
                    out.write_text(svg, encoding="utf-8")
                    print(f"  {out.name}")
                    total += 1
                idx += 1

            for s in f.sequences:
                m = f.get_model(s.model_name)
                prefix = f"{src.stem}-{idx}" if use_index else src.stem
                for suffix, dark in (("light", False), ("dark", True)):
                    svg = render_sequence(s, m, dark=dark)
                    out = src.with_name(f"{prefix}-{suffix}.svg")
                    out.write_text(svg, encoding="utf-8")
                    print(f"  {out.name}")
                    total += 1
                idx += 1

        except Exception as exc:
            print(f"ERROR {src.name}: {exc}", file=sys.stderr)
            errors += 1

    print(f"\n{total} example SVG(s) written from {len(sources)} source(s)", end="")
    if errors:
        print(f"  ({errors} error(s))", file=sys.stderr)


# ---------------------------------------------------------------------------
# Render assets/ from juju docs
# ---------------------------------------------------------------------------

ASSETS_VIEWS = [
    # (ggarch_file, view_name, output_stem)
    ("juju.ggarch",       "K8s deployment topology", "topology"),
    ("juju.ggarch",       "Juju overview",            "overview"),
    ("juju.ggarch",       "Data model",               "data-model"),
    ("juju.ggarch",       "Hook execution",           "hook-execution"),
    ("juju.ggarch",       "Bootstrap K8s",            "bootstrap-k8s"),
    ("juju.ggarch",       "Integrate",                "integrate"),
    ("principles.ggarch", "Forced structure",         "forced-structure"),
    ("principles.ggarch", "Star topology",            "star-topology"),
    ("principles.ggarch", "Execution chain IAAS",     "exec-chain-iaas"),
    ("principles.ggarch", "Notify then pull",         "notify-then-pull"),
    ("principles.ggarch", "Initial event",            "initial-event"),
]


def render_assets(juju_docs: pathlib.Path, assets_dir: pathlib.Path) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Cache parsed files
    parsed: dict[str, object] = {}
    for fname, view_name, stem in ASSETS_VIEWS:
        src = juju_docs / fname
        if fname not in parsed:
            code = src.read_text(encoding="utf-8")
            f = parse(code)
            validate(f)
            parsed[fname] = f
        render_pair(parsed[fname], view_name, assets_dir, stem)


# ---------------------------------------------------------------------------
# Build GIF
# ---------------------------------------------------------------------------

def _rasterize(svg_path: pathlib.Path, png_path: pathlib.Path,
               width: int, height: int, scale: int = 1) -> bool:
    """Rasterize a slide SVG to PNG at width*scale x height*scale.
    Chromium first: cairosvg drops the embedded figure's textPath edge
    labels and marker glyphs when a diagram SVG is embedded raw in a
    slide (round-22 note: rasterize via Chromium). Falls back to
    cairosvg when no Chromium is available. Snap-confined Chromium
    cannot read /tmp, so slides go through ~/.cache."""
    chromium = (shutil.which("chromium")
                or shutil.which("chromium-browser")
                or shutil.which("google-chrome"))
    if chromium:
        # Snap-confined Chromium: hidden dirs (~/.cache) and /tmp are
        # outside the home plug — use a non-hidden dir under home.
        cache = pathlib.Path.home() / "ggarch-raster"
        cache.mkdir(parents=True, exist_ok=True)
        real_svg = cache / svg_path.name
        real_png = cache / png_path.name
        real_svg.write_text(svg_path.read_text(encoding="utf-8"),
                            encoding="utf-8")
        result = subprocess.run(
            [chromium, "--headless", "--disable-gpu", "--no-sandbox",
             "--hide-scrollbars", "--default-background-color=FFFFFFFF",
             f"--force-device-scale-factor={scale}",
             f"--screenshot={real_png}",
             f"--window-size={width},{height}",
             real_svg.as_uri()],
            capture_output=True, timeout=120)
        if result.returncode == 0 and real_png.exists():
            shutil.copyfile(real_png, png_path)
            return True
        print(f"  chromium raster failed "
              f"({result.stderr.decode(errors='ignore')[:200]}) "
              f"-- cairosvg fallback", file=sys.stderr)
    try:
        import cairosvg
    except ImportError:
        return False
    cairosvg.svg2png(url=str(svg_path), write_to=str(png_path),
                     output_width=width*scale, output_height=height*scale)
    return True


# The GIF tells the architecture.md story: one model -> the three narrative
# views -> the directives -> the rendered Sphinx slideshow.
GIF_VIEWS = ["The problem", "The insight", "The topology"]
GIF_SEQUENCE = "juju integrate"


def _gif_source(juju_docs: pathlib.Path) -> str:
    """Source for the GIF views. Try the full docs file first; if this
    ggarch's grammar is older than the file (e.g. `context:` in the
    schema models), fall back to the model "Juju" block plus its
    sequence views, which is all the GIF needs."""
    code = (juju_docs / "juju.ggarch").read_text(encoding="utf-8")
    try:
        parse(code)
        return code
    except ParseError:
        def block_at(start: int) -> str:
            depth = 0
            for i in range(start, len(code)):
                if code[i] == "{":
                    depth += 1
                elif code[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return code[start:i + 1]
            return code[start:]

        start = code.index('model "Juju" {')
        model_block = block_at(start)
        parts = [model_block]
        # Top-level views that draw from the Juju model: multi-line
        # diagram/view blocks and single-line sequence views.
        model_end = start + len(model_block)
        for m in re.finditer(r'^(diagram|view) "[^"]*" from "Juju" \{', code, re.M):
            if m.start() > model_end:
                parts.append(block_at(m.start()))
        for m in re.finditer(r'^sequence "juju [^"]*"\s+from "Juju" \{.*\}$', code, re.M):
            parts.append(m.group(0))
        return "\n".join(parts) + "\n"


def _render_gif_views(juju_docs: pathlib.Path, out_dir: pathlib.Path,
                      dark: bool = False) -> dict[str, pathlib.Path]:
    """Render the GIF's figure SVGs (light or dark theme) into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    f = parse(_gif_source(juju_docs))
    validate(f)
    svgs: dict[str, pathlib.Path] = {}
    for name in GIF_VIEWS:
        d = next(d for d in f.diagrams if d.name == name)
        m  = f.get_model(d.model_name)
        rl = route(solve(d, m), m, d.select)
        svg = render(rl, m, d, dark=dark, skip_legend=True)
        p = out_dir / f"{slug(name)}.svg"
        p.write_text(svg, encoding="utf-8")
        svgs[name] = p
    s = next(s for s in f.sequences if s.name == GIF_SEQUENCE)
    m = f.get_model(s.model_name)
    svg = render_sequence(s, m, dark=dark)
    p = out_dir / f"{slug(GIF_SEQUENCE)}.svg"
    p.write_text(svg, encoding="utf-8")
    svgs[GIF_SEQUENCE] = p
    print(f"  GIF figures: {', '.join(svgs)}")
    return svgs


def build_gif(juju_docs: pathlib.Path, assets_dir: pathlib.Path) -> None:
    """Build the demo GIFs: assets/ggarch-demo.gif and
    assets/ggarch-demo-dark.gif loop at 2.5 s per slide;
    assets/ggarch-demo-once.gif is the dark cut that plays once and
    stops on the QR end slide (for slides). The story: the
    architecture.md walkthrough -- one model, three rendered views,
    the directives, the rendered Sphinx slideshow."""
    try:
        import cairosvg
    except ImportError:
        print("cairosvg not installed -- skipping GIF", file=sys.stderr)
        return

    import drawsvg as dw
    from ggarch.renderer import LABEL_FONT

    ORANGE = "#E95420"
    SLIDE_W = 960; SLIDE_H = 520; PAD = 28
    DELAY = "500"   # centiseconds per slide

    # Slide chrome palettes. The dark BG is the renderer's dark figure
    # background (#1E1E2E), so embedded figures sit flush on the slide.
    THEMES = [
        ("light", False, dict(
            BG="#FFFFFF", PANEL="#F5F5F5", DIVIDER="#CCCCCC",
            TEXT="#222222", MUTED="#666666", BORDER="#DDDDDD",
            FIGBORDER="#EEEEEE", CK=ORANGE, CN="#222222", CM="#999999",
            CBLU="#1050A0", CGRN="#2D7A2D",
            CHROME="#EBEBEB", URLBG="#FFFFFF", URLTEXT="#555555",
            NAVBG="#FAFAFA", DOT="#CCCCCC", BTN="#555555",
            EXPFILL="rgba(255,255,255,0.92)", EXPBORDER="#CCCCCC")),
        ("dark", True, dict(
            BG="#1E1E2E", PANEL="#262636", DIVIDER="#3A3A4E",
            TEXT="#E4E4F4", MUTED="#A0A0B8", BORDER="#3A3A4E",
            FIGBORDER="#3A3A4E", CK=ORANGE, CN="#CDD6F4", CM="#77778A",
            CBLU="#8FA8E8", CGRN="#8CC98C",
            CHROME="#2A2A3A", URLBG="#15151F", URLTEXT="#A0A0B8",
            NAVBG="#23233A", DOT="#55556A", BTN="#CDD6F4",
            EXPFILL="rgba(30,30,46,0.92)", EXPBORDER="#3A3A4E")),
    ]

    figures = {theme: _render_gif_views(juju_docs, ROOT / "build" / "gif" / theme,
                                        dark=dark)
               for theme, dark, _ in THEMES}

    # Per theme: (output name, netscape loop count, delay in
    # centiseconds, ends on the QR slide). All cuts run at 2.5 s.
    # The README pair has no QR end slide; the dark cuts with QR are
    # the looping ggarch-demo-dark-QR.gif and the play-once deck cut.
    DELAY = "250"
    SCALE = 2   # rasterize slides at 2x (1920x1040) so GIF text stays crisp
    THEME_OUTPUTS = {
        "light": [("ggarch-demo.gif", "0", DELAY, False)],
        "dark":  [("ggarch-demo-dark.gif", "0", DELAY, False),
                  ("ggarch-demo-dark-QR.gif", "0", DELAY, True),
                  ("ggarch-demo-once.gif", "1", DELAY, True)],
    }

    def _build_slides(figs, T):
        LGRAY = T["PANEL"]; DGRAY = T["TEXT"]; MUTED = T["MUTED"]
        WHITE = T["BG"]; BORDER = T["BORDER"]
        CK = T["CK"]; CN = T["CN"]; CM = T["CM"]
        CBLU = T["CBLU"]; CGRN = T["CGRN"]

        def _clean(svg):
            svg = re.sub(r'<\?xml[^?]*\?>', '', svg)
            svg = re.sub(r'<!DOCTYPE[^>]*>', '', svg)
            return svg.strip()

        def _header(d, title):
            d.append(dw.Rectangle(0,0,SLIDE_W,SLIDE_H,fill=WHITE))
            d.append(dw.Rectangle(0,0,SLIDE_W,SLIDE_H,fill="none",stroke=BORDER,stroke_width=1))
            d.append(dw.Rectangle(0,0,SLIDE_W,44,fill=ORANGE))
            d.append(dw.Text(title,15,SLIDE_W/2,22,font_family=LABEL_FONT,fill=WHITE,
                             text_anchor="middle",dominant_baseline="central",font_weight="bold"))

        def _code(d, lines, x, y, lh=15):
            for text, color in lines:
                d.append(dw.Text(text,10.5,x,y,font_family="monospace",fill=color,dominant_baseline="auto"))
                y += lh

        def _prose(d, text, x, y, size=9.5, bold=False, color=DGRAY, style="normal",
                   anchor="start"):
            d.append(dw.Text(text,size,x,y,font_family=LABEL_FONT,fill=color,
                             font_weight="bold" if bold else "normal",font_style=style,
                             text_anchor=anchor,dominant_baseline="central"))
            return y + max(16, int(size * 1.35))

        def _embed(d, svg_path, x, y, max_w, max_h):
            """Draw the figure SVG fitted into (max_w, max_h) at (x, y),
            centred horizontally; return (width, height) drawn."""
            svg   = _clean(svg_path.read_text(encoding="utf-8"))
            tw = float(re.search(r'<svg[^>]*width="([0-9.]+)"',  svg).group(1))
            th = float(re.search(r'<svg[^>]*height="([0-9.]+)"', svg).group(1))
            scale = min(max_w/tw, max_h/th)
            w, h = tw*scale, th*scale
            fx = x + (max_w - w)/2
            d.append(dw.Rectangle(fx-2, y, w+4, h+2, fill=WHITE,
                                  stroke=T["FIGBORDER"], stroke_width=1, rx=2))
            inner = re.sub(r'^<svg[^>]*>', '', svg, 1)
            inner = re.sub(r'</svg>\s*$', '', inner)
            d.append(dw.Raw(f'<g transform="translate({fx:.1f},{y:.1f}) scale({scale:.4f})">{inner}</g>'))
            return w, h, fx

        def _expand_button(d, bx, by, btn=20):
            d.append(dw.Rectangle(bx,by,btn,btn,fill=T["EXPFILL"],
                                  stroke=T["EXPBORDER"],stroke_width=1,rx=3))
            d.append(dw.Text("⤢",11,bx+btn/2,by+btn/2,text_anchor="middle",
                             dominant_baseline="central",fill=T["BTN"]))

        # ── Slide 1: juju.ggarch -- one model, written once ─────────────────────
        d1 = dw.Drawing(SLIDE_W, SLIDE_H)
        _header(d1, "juju.ggarch -- one model, written once")
        d1.append(dw.Rectangle(PAD,56,SLIDE_W-PAD*2,SLIDE_H-56-PAD,fill=LGRAY,rx=4))
        col_w = (SLIDE_W-PAD*2-20)//3
        for i in range(1,3):
            divx = PAD + i*(col_w+10) - 5
            d1.append(dw.Line(divx,64,divx,SLIDE_H-PAD-8,stroke=T["DIVIDER"],stroke_width=1))
        cx = [PAD+14+i*(col_w+10) for i in range(3)]
        left = [
            ('model "Juju" {',                                  CK),
            ("  nodes {",                                       CK),
            ('    sre    [type: person, label: "SRE"]',         CN),
            ('    client [type: juju-software,',                CN),
            ('            label: "Client"]',                    CN),
            ('    charmhub [type: external,',                   CN),
            ('              label: "Charmhub"]',                CN),
            ('    clouds [type: external,',                     CN),
            ('            label: "Clouds\\n(AWS, MAAS, ...)",', CN),
            ('            collective: cloud]',                  CN),
            ('    model [type: entity, label: "Model",',        CN),
            ('           deployed: true] {',                    CN),
            ('      application [type: entity] {',              CN),
            ('        unit_node [type: node, label: "Unit"] {', CN),
            ('          unit_agent [type: juju-software,',      CN),
            ('                      label: "Unit agent"]',      CN),
            ('          charm    [type: charm, label: "Charm"]',CN),
            ('          workload [type: workload,',             CN),
            ('                     label: "Workload"]',         CN),
            ("        }",                                       CN),
            ("      }",                                         CN),
            ("    }",                                           CN),
            ("    ...",                                         CM),
            ("  }",                                             CK),
        ]
        mid = [
            ("  edges {",                                       CK),
            ("    sre -> bare_applications",                    CN),
            ('      [type: control, label: "operates"]',        CN),
            ("    user -> juju",                                CN),
            ('      [type: api, label: "declares intent to"]',  CN),
            ("    client -> controller",                        CN),
            ('      [type: api,',                               CN),
            ('       label: "persists goal state in"]',         CN),
            ("    unit_agent -> controller",                    CN),
            ('      [type: stream,',                            CN),
            ('       label: "reconciles state with"]',          CN),
            ("    charm -> workload",                           CN),
            ('      [type: control, label: "operates"]',        CN),
            ("    ...",                                         CM),
            ("  }",                                             CK),
            ("  behaviours {",                                  CK),
            ('    behaviour "integrate" {',                     CK),
            ("      user -> client:",                           CN),
            ('        call "juju integrate foo bar"',           CN),
            ("      client -> controller:",                     CN),
            ('        call "declare the integration"',          CN),
            ("      controller -> agent_foo:",                  CN),
            ('        async "watcher fires"',                   CN),
            ("      controller -> agent_bar:",                  CN),
            ('        async "watcher fires"',                   CN),
            ("      ...",                                       CM),
            ("    }",                                           CK),
            ("  }",                                             CK),
            ("  style { extends: juju }",                       CBLU),
            ("}",                                               CK),
        ]
        right = [
            ('diagram "The problem" from "Juju" {',             CK),
            ("  select {",                                      CK),
            ("    nodes: sre bare_applications",                CN),
            ("    edges: type control",                         CN),
            ("  }",                                             CK),
            ("  positions {",                                   CK),
            ("    sre left-of bare_applications",               CN),
            ("        gap: 120",                                CN),
            ("    sre align-middle bare_applications",          CN),
            ("  }",                                             CK),
            ("}",                                               CK),
            ("",                                                CN),
            ('diagram "The insight" from "Juju" { ... }',       CK),
            ('diagram "The topology" from "Juju" { ... }',      CK),
            ("",                                                CN),
            ('sequence "juju integrate" from "Juju" {',         CK),
            ('  select { behaviour: "integrate" }',             CN),
            ("}",                                               CK),
            ("",                                                CM),
            ("// three views and one slideshow,",               CM),
            ("// all drawn from this one model",                CM),
        ]
        _code(d1, left,  cx[0], 70)
        _code(d1, mid,   cx[1], 70)
        _code(d1, right, cx[2], 70)

        # ── Slides 2-4: three views rendered from the same model ────────────────
        VIEW_SLIDES = [
            ("The problem",
             "rendered from the model: The problem",
             ["An SRE operates applications that run on cloud nodes. Every cloud,",
              "every application, and every link between applications adds its own work."],
             2.1, None),
            ("The insight",
             "rendered from the model: The insight",
             ["Juju sits between the user and the applications. The user declares what",
              "they want, and Juju operates the applications on nodes from clouds."],
             1.6, None),
            ("The topology",
             "rendered from the model: The topology",
             ["The user declares goal state through a client; the controller persists it,",
              "gets nodes from clouds and charms from Charmhub, and the model's unit",
              "agents reconcile with it."],
             None, (880, 330)),
        ]
        view_slides = []
        for name, title, caption, scale, box in VIEW_SLIDES:
            d = dw.Drawing(SLIDE_W, SLIDE_H)
            _header(d, title)
            svg = _clean(figs[name].read_text(encoding="utf-8"))
            tw = float(re.search(r'<svg[^>]*width="([0-9.]+)"',  svg).group(1))
            th = float(re.search(r'<svg[^>]*height="([0-9.]+)"', svg).group(1))
            if box:
                max_w, max_h = box
            else:
                max_w, max_h = tw*scale, th*scale
            disp_h = th * min(max_w/tw, max_h/th)
            # Captions read at the same size as the figure's node labels:
            # LABEL_FONT_SIZE as embedded (scaled), floored for legibility.
            cap_size = max(12, round(LABEL_FONT_SIZE * min(max_w/tw, max_h/th)))
            cap_h = max(16, int(cap_size * 1.35)) * len(caption) + 26
            y0 = max(60, (SLIDE_H - disp_h - cap_h)/2)
            w, h, fx = _embed(d, figs[name], (SLIDE_W-max_w)/2, y0, max_w, max_h)
            cy = y0 + h + 22
            for line in caption:
                _prose(d, line, SLIDE_W/2, cy, size=cap_size, color=MUTED,
                       style="italic", anchor="middle")
                cy += max(16, int(cap_size * 1.35))
            view_slides.append(d)

        # ── Slide 5: explanation/architecture.md -- directives over one model ───
        d5 = dw.Drawing(SLIDE_W, SLIDE_H)
        _header(d5, "explanation/architecture.md")
        d5.append(dw.Rectangle(PAD,56,SLIDE_W-PAD*2,SLIDE_H-56-PAD,fill=LGRAY,rx=4))
        md = [
            ("",                                                                  CN),
            ("## The basic topology",                                             CGRN),
            ("",                                                                  CN),
            ("```{ggarch}",                                                       CK),
            (":file: ../juju.ggarch",                                             CBLU),
            (":view: The topology",                                               CBLU),
            (":caption: The user tells the client what they want, and the client",CBLU),
            ("          sends it to the controller, which stores it as the",      CBLU),
            ("          goal state.",                                             CBLU),
            ("```",                                                               CK),
            ("",                                                                  CN),
            ("## Under the hood",                                                 CGRN),
            ("",                                                                  CN),
            ("`````{tabs}",                                                       CK),
            ("`````{tab} Kubernetes",                                             CK),
            ("",                                                                  CN),
            ("```{ggarch}",                                                       CK),
            (":file: ../juju.ggarch",                                             CBLU),
            (":slides: juju add-k8s | juju bootstrap (Kubernetes) |",             CBLU),
            ("         juju add-model | juju deploy (Kubernetes) |",              CBLU),
            ("         juju config | juju integrate",                             CBLU),
            (":slide-captions: The user starts by connecting a Kubernetes | ...", CBLU),
            ("```",                                                               CK),
            ("",                                                                  CN),
            ("// :view: picks a diagram; :slides: turns a list of",               CM),
            ("// sequence views into a carousel with captions",                   CM),
        ]
        _code(d5, md, PAD+20, 68)

        # ── Slide 6: the rendered Sphinx page with the slideshow ────────────────
        d6 = dw.Drawing(SLIDE_W, SLIDE_H)
        _header(d6, "http://127.0.0.1:8000/explanation/architecture/")

        chrome_y=50; chrome_h=28
        d6.append(dw.Rectangle(PAD,chrome_y,SLIDE_W-PAD*2,chrome_h,
                                fill=T["CHROME"],stroke=T["DIVIDER"],stroke_width=1,rx=3))
        url_x=PAD+12; url_w=SLIDE_W-PAD*2-24
        d6.append(dw.Rectangle(url_x,chrome_y+4,url_w,20,
                                fill=T["URLBG"],stroke=T["DIVIDER"],stroke_width=1,rx=3))
        d6.append(dw.Text("🔒  http://127.0.0.1:8000/explanation/architecture/",
                           9,url_x+8,chrome_y+14,font_family="monospace",fill=T["URLTEXT"],
                           dominant_baseline="central"))

        page_top=chrome_y+chrome_h+4; page_h=SLIDE_H-page_top-PAD
        d6.append(dw.Rectangle(PAD,page_top,SLIDE_W-PAD*2,page_h,fill=WHITE,stroke=BORDER,stroke_width=1))

        NAV_W=120; nav_x=PAD+1
        d6.append(dw.Rectangle(nav_x,page_top+1,NAV_W,page_h-2,fill=T["NAVBG"],stroke=BORDER,stroke_width=1))
        d6.append(dw.Text("Architecture",9,nav_x+10,page_top+18,font_family=LABEL_FONT,
                           fill=ORANGE,font_weight="bold",dominant_baseline="central"))
        for i,(item,col,bold) in enumerate([
            ("Overview",      MUTED,  False),
            ("The problem",   MUTED,  False),
            ("The insight",   MUTED,  False),
            ("The topology",  MUTED,  False),
            ("Under the hood",ORANGE, True),
        ]):
            d6.append(dw.Text(item,8,nav_x+14,page_top+36+i*17,font_family=LABEL_FONT,
                               fill=col,font_weight="bold" if bold else "normal",
                               dominant_baseline="central"))

        cx6=PAD+NAV_W+16; cw6=SLIDE_W-PAD-NAV_W-PAD-16
        y = page_top+16
        y = _prose(d6,"Juju architecture",cx6,y,size=13,bold=True); y+=2
        y = _prose(d6,"Under the hood -- Kubernetes",cx6,y,size=11,bold=True); y+=6

        fig_max_w=cw6-8; fig_max_h=page_h-(y-page_top)-64
        w6, h6, fx6 = _embed(d6, figs[GIF_SEQUENCE], cx6, y, fig_max_w, fig_max_h)
        _expand_button(d6, fx6+w6-25, y+5)

        # slideshow controls: prev/next arrows and one dot per slide, last active
        dots_y = y + h6 + 16
        n_dots = 6; dot_r = 3; dot_gap = 12
        dots_w = n_dots*dot_gap
        cx_dots = cx6 + (cw6 - dots_w)/2 + 14
        d6.append(dw.Text("‹",13,cx_dots-24,dots_y,text_anchor="middle",
                          dominant_baseline="central",fill=T["MUTED"]))
        d6.append(dw.Text("›",13,cx_dots+dots_w+10,dots_y,text_anchor="middle",
                          dominant_baseline="central",fill=T["BTN"]))
        for i in range(n_dots):
            col = ORANGE if i == n_dots-1 else T["DOT"]
            d6.append(dw.Circle(cx_dots+i*dot_gap, dots_y, dot_r, fill=col))
        cy = dots_y + 18
        for line in ["Finally, the user integrates two applications so that they work together. The controller",
                     "persists the integration, and the watchers of both applications fire."]:
            _prose(d6, line, cx6, cy, size=12, color=MUTED)
            cy += 16

        # ── Slide 7: QR to the repo (only in the QR cuts) ───────────────────────
        slides = [d1, *view_slides, d5, d6]
        qr_path = ROOT / "assets" / "ggarch-QR.png"
        if not qr_path.exists():
            return slides, slides
        d7 = dw.Drawing(SLIDE_W, SLIDE_H)
        _header(d7, "scan to try ggarch")
        qr_size = 320
        card = qr_size + 48
        cx7 = (SLIDE_W - card) / 2
        cy7 = max(70, (SLIDE_H - card - 60) / 2)
        # QR codes need a light, uniform background to scan: keep the
        # card white in both themes.
        d7.append(dw.Rectangle(cx7, cy7, card, card, fill="#FFFFFF",
                               stroke=T["FIGBORDER"], stroke_width=1, rx=6))
        qr_b64 = base64.b64encode(qr_path.read_bytes()).decode("ascii")
        d7.append(dw.Raw(
            f'<image x="{cx7+24:.1f}" y="{cy7+24:.1f}" '
            f'width="{qr_size}" height="{qr_size}" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'xlink:href="data:image/png;base64,{qr_b64}"/>'))
        _prose(d7, "https://github.com/tmihoc/ggarch",
               SLIDE_W / 2, cy7 + card + 34, size=14, color=T["TEXT"],
               anchor="middle")
        return slides, slides + [d7]

    # ── Convert to PNG and assemble the GIFs ────────────────────────────────
    for theme, dark, T in THEMES:
        slides, slides_qr = _build_slides(figures[theme], T)
        slides_dir = ROOT / "build" / "gif" / theme
        slides_dir.mkdir(parents=True, exist_ok=True)

        def _pngs(slide_list, start=1):
            out = []
            for i, slide in enumerate(slide_list, start):
                svg_path = slides_dir / f"slide{i}.svg"
                png_path = slides_dir / f"slide{i}.png"
                slide.save_svg(str(svg_path))
                # Chromium collapses runs of spaces in <text> unless they
                # are marked whitespace-preserving; the code slides rely
                # on indent.
                svg_txt = svg_path.read_text(encoding="utf-8")
                svg_path.write_text(
                    svg_txt.replace("<text ", '<text xml:space="preserve" '),
                    encoding="utf-8")
                if not _rasterize(svg_path, png_path, SLIDE_W, SLIDE_H,
                                  SCALE):
                    print("no rasterizer available -- skipping GIF",
                          file=sys.stderr)
                    return None
                out.append(str(png_path))
            return out

        png_sets = {False: _pngs(slides)}
        if png_sets[False] is None:
            return
        if slides_qr is not slides:
            png_sets[True] = png_sets[False] + _pngs(slides_qr[-1:],
                                                     start=len(slides) + 1)

        for name, loop, delay, with_qr in THEME_OUTPUTS[theme]:
            pngs = png_sets.get(with_qr, png_sets[False])
            gif_path = assets_dir / name
            args = ["convert"]
            for png in pngs:
                args += ["-delay", delay, png]
            args += ["-loop", loop, "-layers", "optimize", str(gif_path)]
            result = subprocess.run(args, capture_output=True)
            if result.returncode != 0:
                print(f"GIF error: {result.stderr.decode()}", file=sys.stderr)
            else:
                size = gif_path.stat().st_size // 1024
                print(f"  {name}  ({size} KB, "
                      f"{len(pngs)} slides x {int(delay)/100:.1f} s)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--juju-docs", metavar="PATH",
                   help="Path to juju docs directory (contains juju.ggarch)")
    p.add_argument("--gif", action="store_true",
                   help="Build assets/ggarch-demo.gif (requires cairosvg + ImageMagick)")
    p.add_argument("--no-examples", action="store_true",
                   help="Skip re-rendering examples/")
    args = p.parse_args()

    if not args.no_examples:
        print("Rendering examples/")
        render_examples()

    if args.juju_docs:
        juju_docs  = pathlib.Path(args.juju_docs).expanduser().resolve()
        assets_dir = ROOT / "assets"
        print(f"\nRendering assets/ from {juju_docs}")
        render_assets(juju_docs, assets_dir)

        if args.gif:
            print("\nBuilding GIF")
            build_gif(juju_docs, assets_dir)
    elif args.gif:
        print("--gif requires --juju-docs", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
