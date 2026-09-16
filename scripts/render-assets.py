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

  assets/ggarch-demo.gif
    Three-slide README walkthrough built from the assets SVGs.
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
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ggarch import parse, validate, solve, route, render
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

def build_gif(assets_dir: pathlib.Path) -> None:
    try:
        import cairosvg
    except ImportError:
        print("cairosvg not installed -- skipping GIF", file=sys.stderr)
        return

    import drawsvg as dw
    from ggarch.renderer import LABEL_FONT

    ORANGE = "#E95420"; LGRAY = "#F5F5F5"; DGRAY = "#222222"
    MUTED  = "#666666"; WHITE = "#FFFFFF"; BORDER = "#DDDDDD"
    CBLU   = "#1050A0"; CGRN  = "#2D7A2D"
    SLIDE_W = 960; SLIDE_H = 520; PAD = 28
    CK = ORANGE; CN = DGRAY; CM = "#999999"

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

    def _code(d, lines, x, y, lh=16):
        for text, color in lines:
            d.append(dw.Text(text,11,x,y,font_family="monospace",fill=color,dominant_baseline="auto"))
            y += lh

    def _prose(d, text, x, y, size=9.5, bold=False, color=DGRAY):
        d.append(dw.Text(text,size,x,y,font_family=LABEL_FONT,fill=color,
                         font_weight="bold" if bold else "normal",dominant_baseline="central"))
        return y + 16

    # ── Slide 1: juju.ggarch source ─────────────────────────────────────────
    d1 = dw.Drawing(SLIDE_W, SLIDE_H)
    _header(d1, "juju.ggarch")
    d1.append(dw.Rectangle(PAD,56,SLIDE_W-PAD*2,SLIDE_H-56-PAD,fill=LGRAY,rx=4))
    col_w = (SLIDE_W-PAD*2-20)//3
    for i in range(1,3):
        divx = PAD + i*(col_w+10) - 5
        d1.append(dw.Line(divx,64,divx,SLIDE_H-PAD-8,stroke="#CCCCCC",stroke_width=1))
    cx = [PAD+14+i*(col_w+10) for i in range(3)]
    left = [
        ("nodes {",                                         CK),
        ("  controller_pod [type: container] {",           CK),
        ("    jujud [type: juju-software,",                CN),
        ('           label: "Controller agent"]',          CN),
        ("  }",                                            CK),
        ("  unit_agent  [type: juju-software,",            CN),
        ('              label: "Unit agent"]',             CN),
        ("  charm       [type: charm,",                    CN),
        ('              label: "Charm"]',                  CN),
        ("  pebble      [type: pebble,",                   CN),
        ('              label: "Pebble (init)",',          CN),
        ("              lifecycle: init]",                 CN),
        ("  k8s         [type: external,",                 CN),
        ('              label: "Kubernetes cloud"]',       CN),
        ("  charmhub    [type: external,",                 CN),
        ('              label: "Charmhub"]',               CN),
        ("  ...",                                          CM),
        ("",                                               CN),
        ("edges {",                                        CK),
        ("  jujud -> k8s       [type: control,",           CN),
        ('                      label: "provisions on"]',  CN),
        ("  charm -> pebble",                              CN),
        ("    [type: api,",                                CN),
        ('     label: "calls Pebble API"]',                CN),
        ("  ...",                                          CM),
    ]
    mid = [
        ("behaviours {",                                   CK),
        ('  behaviour "Hook execution" {',                 CK),
        ("    apiserver -> unit_agent:",                   CN),
        ('      async "watcher fires"',                    CN),
        ("    unit_agent -> unit_agent:",                  CN),
        ('      self "snapshot remote state"',             CN),
        ("    unit_agent -> charm:",                       CN),
        ('      call "exec dispatch"',                     CN),
        ('    loop "during hook" {',                       CBLU),
        ("      charm -> unit_agent:",                     CN),
        ('        call "hook command"',                    CN),
        ("      unit_agent -> apiserver:",                 CN),
        ('        call "serve via API"',                   CN),
        ("    }",                                          CBLU),
        ('    alt "exit 0" {',                             CBLU),
        ("      ...",                                      CM),
        ("    } else \"failure\" {",                       CBLU),
        ("      ...",                                      CM),
        ("    }",                                          CBLU),
        ("  }",                                            CK),
        ("  ...",                                          CM),
    ]
    right = [
        ("diagram \"K8s topology\"",                       CK),
        ("    from \"Juju\" {",                            CK),
        ("  select {",                                     CK),
        ("    nodes: k8s controller_pod",                  CN),
        ("           unit_pod charmhub",                   CN),
        ("    edges: type api type control",               CN),
        ("  }",                                            CK),
        ("  positions {",                                  CK),
        ("    controller_pod",                             CN),
        ("      left-of unit_pod gap: 60",                 CN),
        ("    k8s above controller_pod",                   CN),
        ("    charmhub below controller_pod",              CN),
        ("    unit_pod direction: right",                  CN),
        ("  }",                                            CK),
        ("}",                                              CK),
        ("",                                               CN),
        ("view \"Hook execution\"",                        CK),
        ("    from \"Juju\" {",                            CK),
        ("  select {",                                     CK),
        ('    behaviour: "Hook execution"',                CN),
        ("  }",                                            CK),
        ("}",                                              CK),
        ("",                                               CM),
        ("// :view: works for both",                       CM),
        ("// diagrams and sequences",                      CM),
    ]
    _code(d1, left,  cx[0], 72)
    _code(d1, mid,   cx[1], 72)
    _code(d1, right, cx[2], 72)

    # ── Slide 2: explanation/architecture.md ────────────────────────────────
    d2 = dw.Drawing(SLIDE_W, SLIDE_H)
    _header(d2, "explanation/architecture.md")
    d2.append(dw.Rectangle(PAD,56,SLIDE_W-PAD*2,SLIDE_H-56-PAD,fill=LGRAY,rx=4))
    md = [
        ("",                                                                  CN),
        ("# Juju architecture",                                               CGRN),
        ("",                                                                  CN),
        ("The key insight is the separation of two concerns that are usually", CN),
        ("tangled. Cloud knowledge -- how to get a machine, attach storage,", CN),
        ("configure networking -- stays on the cloud side. Application",      CN),
        ("knowledge stays in charms, reusable packages published on",         CN),
        ("Charmhub. Juju sits between the user and both sides.",              CN),
        ("",                                                                  CN),
        ("The second separation is between intent and execution. You declare",CN),
        ("what you want; Juju stores that as goal state and drives the real", CN),
        ("world toward it continuously -- through restarts, failures, drift.",CN),
        ("",                                                                  CN),
        ("## Topology",                                                       CGRN),
        ("",                                                                  CN),
        ("A live Juju deployment has a controller -- the management process", CN),
        ("that holds all goal state -- and one or more applications, each",   CN),
        ("broken into one or more units. Every unit runs the same chain: a", CN),
        ("unit agent drives a charm, which operates the workload.",           CN),
        ("",                                                                  CN),
        ("```{ggarch}",                                                       CK),
        (":file: juju.ggarch",                                                CBLU),
        (":view: K8s deployment topology",                                    CBLU),
        (":caption: Controller pod (left); unit pod (right) with",            CBLU),
        ("          charm container and workload container.",                 CBLU),
        ("```",                                                               CK),
    ]
    _code(d2, md, PAD+20, 66, lh=15)

    # ── Slide 3: rendered Sphinx page ────────────────────────────────────────
    topo_svg   = (assets_dir / "topology-light.svg").read_text(encoding="utf-8")
    topo_clean = _clean(topo_svg)
    tw = float(re.search(r'<svg[^>]*width="([0-9.]+)"',  topo_clean).group(1))
    th = float(re.search(r'<svg[^>]*height="([0-9.]+)"', topo_clean).group(1))

    d3 = dw.Drawing(SLIDE_W, SLIDE_H)
    _header(d3, "http://127.0.0.1:8000/explanation/architecture/")

    chrome_y=50; chrome_h=28
    d3.append(dw.Rectangle(PAD,chrome_y,SLIDE_W-PAD*2,chrome_h,
                            fill="#EBEBEB",stroke="#CCCCCC",stroke_width=1,rx=3))
    url_x=PAD+12; url_w=SLIDE_W-PAD*2-24
    d3.append(dw.Rectangle(url_x,chrome_y+4,url_w,20,
                            fill=WHITE,stroke="#CCCCCC",stroke_width=1,rx=3))
    d3.append(dw.Text("🔒  http://127.0.0.1:8000/explanation/architecture/",
                       9,url_x+8,chrome_y+14,font_family="monospace",fill="#555555",
                       dominant_baseline="central"))

    page_top=chrome_y+chrome_h+4; page_h=SLIDE_H-page_top-PAD
    d3.append(dw.Rectangle(PAD,page_top,SLIDE_W-PAD*2,page_h,fill=WHITE,stroke=BORDER,stroke_width=1))

    NAV_W=120; nav_x=PAD+1
    d3.append(dw.Rectangle(nav_x,page_top+1,NAV_W,page_h-2,fill="#FAFAFA",stroke=BORDER,stroke_width=1))
    d3.append(dw.Text("Architecture",9,nav_x+10,page_top+18,font_family=LABEL_FONT,
                       fill=ORANGE,font_weight="bold",dominant_baseline="central"))
    for i,(item,col,bold) in enumerate([
        ("Overview",    MUTED,  False),
        ("Topology",    ORANGE, True),
        ("Hook execution",MUTED,False),
        ("Data model",  MUTED,  False),
    ]):
        d3.append(dw.Text(item,8,nav_x+14,page_top+36+i*17,font_family=LABEL_FONT,
                           fill=col,font_weight="bold" if bold else "normal",
                           dominant_baseline="central"))

    cx3=PAD+NAV_W+16; cw3=SLIDE_W-PAD-NAV_W-PAD-16
    y = page_top+18
    y = _prose(d3,"Juju architecture",cx3,y,size=13,bold=True); y+=4
    y = _prose(d3,"A live Juju deployment has a controller -- the management process that holds all",cx3,y)
    y = _prose(d3,"goal state -- and one or more applications, each broken into one or more units.",cx3,y)
    y = _prose(d3,"Every unit runs the same chain: a unit agent drives a charm, which operates the",cx3,y)
    y = _prose(d3,"workload. The controller is the single point through which all integration flows.",cx3,y)
    y+=8
    y = _prose(d3,"Topology",cx3,y,size=11,bold=True); y+=2
    y = _prose(d3,"On Kubernetes, Juju provisions pods for its own processes. The controller pod runs",cx3,y)
    y = _prose(d3,"the controller agent; each unit gets its own pod with a charm container and a",cx3,y)
    y = _prose(d3,"workload container.",cx3,y)
    y+=8

    fig_max_w=cw3*0.88; scale3=min(fig_max_w/tw,(page_h-(y-page_top)-32)/th)
    dw3=tw*scale3; dh3=th*scale3
    fig_x=cx3+(cw3-dw3)/2; fig_y=y

    d3.append(dw.Rectangle(fig_x-2,fig_y,dw3+4,dh3+2,fill=WHITE,stroke="#EEEEEE",stroke_width=1,rx=2))
    inner3=re.sub(r'^<svg[^>]*>','',topo_clean,1)
    inner3=re.sub(r'</svg>\s*$','',inner3)
    d3.append(dw.Raw(f'<g transform="translate({fig_x:.1f},{fig_y:.1f}) scale({scale3:.4f})">{inner3}</g>'))

    btn=20; bx=fig_x+dw3-btn-5; by=fig_y+5
    d3.append(dw.Rectangle(bx,by,btn,btn,fill="rgba(255,255,255,0.92)",stroke="#CCCCCC",stroke_width=1,rx=3))
    d3.append(dw.Text("⤢",11,bx+btn/2,by+btn/2,text_anchor="middle",dominant_baseline="central",fill="#555555"))
    d3.append(dw.Text("Controller pod (left); unit pod (right) with charm container and workload container.",
                       8.5,fig_x,fig_y+dh3+13,font_family=LABEL_FONT,fill=MUTED,
                       font_style="italic",dominant_baseline="central"))

    # ── Convert to PNG and assemble GIF ─────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        pngs = []
        for i, slide in enumerate([d1, d2, d3], 1):
            svg_path = pathlib.Path(tmp) / f"slide{i}.svg"
            png_path = pathlib.Path(tmp) / f"slide{i}.png"
            slide.save_svg(str(svg_path))
            cairosvg.svg2png(url=str(svg_path), write_to=str(png_path),
                             output_width=SLIDE_W, output_height=SLIDE_H)
            pngs.append(str(png_path))

        gif_path = assets_dir / "ggarch-demo.gif"
        args = ["convert"]
        for png in pngs:
            args += ["-delay", "350", png]
        args += ["-loop", "0", "-layers", "optimize", str(gif_path)]
        result = subprocess.run(args, capture_output=True)
        if result.returncode != 0:
            print(f"GIF error: {result.stderr.decode()}", file=sys.stderr)
        else:
            size = gif_path.stat().st_size // 1024
            print(f"  ggarch-demo.gif  ({size} KB)")


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
            build_gif(assets_dir)
    elif args.gif:
        print("--gif requires --juju-docs", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
