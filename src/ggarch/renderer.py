"""ggarch SVG renderer.

Renders a RoutedLayout into two SVG strings: one for light mode, one for dark.

SVG structure per diagram:
  <svg viewBox="…" xmlns="…">
    <defs>                    <!-- arrowhead markers -->
    </defs>
    <g class="ggarch-nodes">
      <!-- containers first (background), then leaves -->
    </g>
    <g class="ggarch-edges">
      <!-- polylines with arrowheads -->
    </g>
    <g class="ggarch-annotations">
      <!-- box / callout / separator overlays -->
    </g>
  </svg>

We use drawsvg for SVG generation. All user-supplied strings are escaped via
drawsvg's own XML escaping before being written into text elements.
"""
from __future__ import annotations

import math
from typing import Sequence

import drawsvg as dw

from ggarch.layout import FONT_SIZE, Rect, SolvedLayout, SolvedNode
from ggarch.model import (
    AnnotationBox,
    AnnotationBadge,
    AnnotationCallout,
    AnnotationSeparator,
    DiagramView,
    Model,
)
from ggarch.presets import NodeStyle, ResolvedStyle, get_preset, resolve_style
from ggarch.router import RoutedEdge, RoutedLayout


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MARGIN          = 20    # px — white-space margin around the diagram
ARROWHEAD_SIZE  = 8     # px
LABEL_FONT      = "'Ubuntu Sans', Ubuntu, system-ui, -apple-system, sans-serif"
ANNOTATION_FONT = "'Ubuntu Sans', Ubuntu, system-ui, -apple-system, sans-serif"



# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render(
    routed: RoutedLayout,
    model: Model,
    view: DiagramView,
    dark: bool = False,
) -> str:
    """Render a RoutedLayout to an SVG string.

    dark=False → light mode; dark=True → dark mode.
    Returns a UTF-8 SVG string.
    """
    preset = get_preset(model.style.extends)
    node_styles = resolve_style(model.style, dark=dark)

    layout = routed.layout
    bounds = layout.bounds

    vw = bounds.w + MARGIN * 2
    vh = bounds.h + MARGIN * 2
    ox = MARGIN - bounds.x   # translate so diagram starts at (MARGIN, MARGIN)
    oy = MARGIN - bounds.y

    bg = "#1E1E2E" if dark else "#FFFFFF"
    drawing = dw.Drawing(vw, vh, origin=(0, 0))
    drawing.append(dw.Rectangle(0, 0, vw, vh, fill=bg))
    _add_arrowhead_defs(drawing, dark, preset)

    nodes_g = dw.Group(id="ggarch-nodes")
    edges_g = dw.Group(id="ggarch-edges")
    ann_g   = dw.Group(id="ggarch-annotations")
    _render_nodes(nodes_g, layout.nodes, node_styles, ox, oy, view)

    # Render edges.
    for edge in routed.edges:
        _render_edge(edges_g, edge, preset, dark, ox, oy)

    # Render annotations.
    for ann in view.annotations:
        _render_annotation(ann_g, ann, layout, ox, oy, dark)

    drawing.append(nodes_g)
    drawing.append(edges_g)
    drawing.append(ann_g)

    return drawing.as_svg()


# ---------------------------------------------------------------------------
# Arrowhead markers
# ---------------------------------------------------------------------------

def _add_arrowhead_defs(
    drawing: dw.Drawing,
    dark: bool,
    preset: ResolvedStyle,
) -> None:
    arrow_color = "#AAAAAA" if dark else "#555555"
    s = ARROWHEAD_SIZE
    # refX=s places the tip of the triangle (at x=s) on the path endpoint.
    # refY=s/2 centres the triangle vertically on the path.
    marker = dw.Marker(0, 0, s, s, scale=1, orient="auto", id="arrow",
                       refX=s, refY=s / 2)
    marker.append(dw.Lines(
        0, 0,
        s, s / 2,
        0, s,
        fill=arrow_color,
        close=True,
    ))
    drawing.append_def(marker)


# ---------------------------------------------------------------------------
# Node rendering
# ---------------------------------------------------------------------------

def _render_nodes(
    g: dw.Group,
    nodes: list[SolvedNode],
    node_styles: dict[str, NodeStyle],
    ox: float,
    oy: float,
    view: DiagramView,
) -> None:
    # Render containers (nodes with children) first so they appear behind.
    for node in nodes:
        if node.children:
            _render_node(g, node, node_styles, ox, oy, view)
    for node in nodes:
        if not node.children:
            _render_node(g, node, node_styles, ox, oy, view)


def _render_node(
    g: dw.Group,
    node: SolvedNode,
    node_styles: dict[str, NodeStyle],
    ox: float,
    oy: float,
    view: DiagramView,
) -> None:
    style = node_styles.get(node.type, node_styles.get("default", NodeStyle()))
    r = node.rect
    x, y, w, h = r.x + ox, r.y + oy, r.w, r.h

    has_children = bool(node.children)
    if style.shape == "person":
        _render_person(g, x, y, w, h, style, node.label)
    elif style.shape == "cylinder":
        _render_cylinder(g, x, y, w, h, style, node.label)
    else:
        _render_box(g, x, y, w, h, style, node.label, node.lifecycle,
                    is_container=has_children)

    # Render children on top.
    if node.children:
        _render_nodes(g, node.children, node_styles, ox, oy, view)

    # Cardinality badge.
    if node.cardinality:
        _render_cardinality_badge(g, x + w - 4, y + 4, node.cardinality)


def _lifecycle_stroke_dash(lifecycle: str) -> str:
    return {"init": "6,3", "ephemeral": "2,2"}.get(lifecycle, "")

def _render_box(
    g: dw.Group,
    x: float, y: float, w: float, h: float,
    style: NodeStyle,
    label: str,
    lifecycle: str = "persistent",
    is_container: bool = False,
) -> None:
    from ggarch.layout import CONTAINER_PAD_TOP
    fill   = style.fill if style.fill != "none" else "none"
    stroke = style.stroke
    stroke_dash = style.stroke_dash or _lifecycle_stroke_dash(lifecycle)
    stroke_width = style.stroke_width

    rect_kwargs: dict = dict(
        fill=fill,
        stroke=stroke,
        stroke_width=stroke_width,
        rx=style.border_radius,
        ry=style.border_radius,
    )
    if stroke_dash:
        rect_kwargs["stroke_dasharray"] = stroke_dash

    g.append(dw.Rectangle(x, y, w, h, **rect_kwargs))

    if is_container:
        # Label in the header strip above children.
        label_y = y + CONTAINER_PAD_TOP / 2
        _render_label(g, x + w / 2, label_y, label, style)
    else:
        _render_label(g, x + w / 2, y + h / 2, label, style)


# Fixed size for the person figure — independent of solver-allocated height.
_PERSON_SIZE = 56   # px total height (figure + label)


def _render_person(
    g: dw.Group,
    x: float, y: float, w: float, h: float,
    style: NodeStyle,
    label: str,
) -> None:
    """Stick-figure person icon, fixed size, centred in allocated rect.

    The label is placed below the legs, not inside the figure area.
    The allocated rect height may be larger than the figure (solver
    gives the person node the same height as its row neighbours);
    the figure itself is drawn at the top of the allocated rect and
    the label sits below the legs with a small gap.
    """
    cx  = x + w / 2
    fy  = y                         # figure starts at top of allocated rect
    fh  = _PERSON_SIZE * 0.78       # figure body height (no label in fh)
    fw  = fh * 0.7

    head_r  = fh * 0.18
    head_cy = fy + head_r + 2
    g.append(dw.Circle(cx, head_cy, head_r,
                       fill="none", stroke=style.font_color, stroke_width=1.5))
    body_top = head_cy + head_r
    body_bot = fy + fh * 0.60
    g.append(dw.Line(cx, body_top, cx, body_bot,
                     stroke=style.font_color, stroke_width=1.5))
    arm_y = body_top + (body_bot - body_top) * 0.35
    g.append(dw.Line(cx - fw * 0.35, arm_y, cx + fw * 0.35, arm_y,
                     stroke=style.font_color, stroke_width=1.5))
    leg_bot = fy + fh * 0.95
    g.append(dw.Line(cx, body_bot, cx - fw * 0.30, leg_bot,
                     stroke=style.font_color, stroke_width=1.5))
    g.append(dw.Line(cx, body_bot, cx + fw * 0.30, leg_bot,
                     stroke=style.font_color, stroke_width=1.5))
    # Label below the legs with a small gap.
    _render_label(g, cx, leg_bot + 10, label, style,
                  anchor="middle", baseline="hanging")


def _render_cylinder(
    g: dw.Group,
    x: float, y: float, w: float, h: float,
    style: NodeStyle,
    label: str,
) -> None:
    """Database cylinder: rect with ellipses at top and bottom."""
    ry = min(h * 0.15, 12)
    fill   = style.fill if style.fill != "none" else "none"
    stroke = style.stroke
    sw     = style.stroke_width
    # Body rect (no top/bottom stroke on the sides of the ellipse).
    g.append(dw.Rectangle(x, y + ry, w, h - ry * 2,
                          fill=fill, stroke=stroke, stroke_width=sw))
    # Bottom ellipse.
    g.append(dw.Ellipse(x + w / 2, y + h - ry, w / 2, ry,
                        fill=fill, stroke=stroke, stroke_width=sw))
    # Top ellipse (filled to cover the body rect top edge).
    g.append(dw.Ellipse(x + w / 2, y + ry, w / 2, ry,
                        fill=fill, stroke=stroke, stroke_width=sw))
    _render_label(g, x + w / 2, y + h / 2, label, style)


def _render_label(
    g: dw.Group,
    cx: float,
    cy: float,
    label: str,
    style: NodeStyle,
    anchor: str = "middle",
    baseline: str = "central",
) -> None:
    lines = label.split("\\n")
    lh = style.font_size * 1.4
    total_h = lh * len(lines)
    start_y = cy - total_h / 2 + lh * 0.5
    for i, line in enumerate(lines):
        g.append(dw.Text(
            line,
            style.font_size,
            cx,
            start_y + i * lh,
            font_family=LABEL_FONT,
            fill=style.font_color,
            text_anchor=anchor,
            dominant_baseline=baseline if i == 0 else "central",
        ))


# ---------------------------------------------------------------------------
# Cardinality badge
# ---------------------------------------------------------------------------

def _render_cardinality_badge(
    g: dw.Group,
    x: float,
    y: float,
    cardinality: str,
) -> None:
    short = {
        "one-per-deployment": "×1",
        "one-per-model":      "×1/model",
        "one-per-application":"×1/app",
        "one-per-unit":       "×n",
        "one-per-host":       "×1/host",
    }.get(cardinality, f"×{cardinality}")
    badge_w = len(short) * 6 + 8
    badge_h = 14
    g.append(dw.Rectangle(x - badge_w, y, badge_w, badge_h,
                          fill="#444", stroke="none", rx=3, ry=3))
    g.append(dw.Text(short, 9, x - badge_w / 2, y + badge_h / 2,
                     font_family=LABEL_FONT, fill="#EEE",
                     text_anchor="middle", dominant_baseline="central"))


# ---------------------------------------------------------------------------
# Edge rendering
# ---------------------------------------------------------------------------

def _render_edge(
    g: dw.Group,
    edge: RoutedEdge,
    preset: ResolvedStyle,
    dark: bool,
    ox: float,
    oy: float,
) -> None:
    es = preset.edge(edge.edge_type, dark=dark)
    pts = [(p.x + ox, p.y + oy) for p in edge.points]

    # Build path data.
    d_parts = [f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"]
    for px, py in pts[1:]:
        d_parts.append(f"L {px:.1f} {py:.1f}")
    d = " ".join(d_parts)

    path_kwargs: dict = dict(
        fill="none",
        stroke=es.stroke,
        stroke_width=es.stroke_width,
    )
    if edge.style == "dashed" or es.stroke_dash:
        path_kwargs["stroke_dasharray"] = es.stroke_dash or "6,3"
    elif edge.style == "dotted":
        path_kwargs["stroke_dasharray"] = "2,2"

    if edge.arrow in ("forward", "both"):
        path_kwargs["marker_end"] = "url(#arrow)"
    if edge.arrow in ("back", "both"):
        path_kwargs["marker_start"] = "url(#arrow)"

    g.append(dw.Path(d=d, **path_kwargs))

    # Edge label: offset 12px perpendicular to the edge direction.
    if edge.label:
        mid = edge.mid
        mx, my = mid.x + ox, mid.y + oy
        dx = edge.end.x - edge.start.x
        dy = edge.end.y - edge.start.y
        length = max(abs(dx) + abs(dy), 1)
        # Perpendicular unit vector (rotate 90° CCW).
        nx, ny = -dy / length, dx / length
        lx = mx + nx * 12
        ly = my + ny * 12
        label_bg = "#1E1E2E" if dark else "#FFFFFF"
        lw = len(edge.label) * 6.5
        g.append(dw.Rectangle(lx - lw / 2 - 3, ly - 9, lw + 6, 14,
                               fill=label_bg, stroke="none",
                               fill_opacity=1))
        g.append(dw.Text(
            edge.label, es.font_size, lx, ly,
            font_family=LABEL_FONT,
            fill=es.font_color,
            text_anchor="middle",
            dominant_baseline="central",
        ))

# ---------------------------------------------------------------------------
# Annotation rendering
# ---------------------------------------------------------------------------

def _render_annotation(
    g: dw.Group,
    ann,
    layout: SolvedLayout,
    ox: float,
    oy: float,
    dark: bool,
) -> None:
    if isinstance(ann, AnnotationBox):
        _render_ann_box(g, ann, layout, ox, oy, dark)
    elif isinstance(ann, AnnotationCallout):
        _render_ann_callout(g, ann, layout, ox, oy, dark)
    elif isinstance(ann, AnnotationSeparator):
        _render_ann_separator(g, ann, layout, ox, oy, dark)
    elif isinstance(ann, AnnotationBadge):
        _render_ann_badge(g, ann, layout, ox, oy, dark)


def _nodes_bounding_rect(node_ids: list[str], layout: SolvedLayout) -> Rect | None:
    rects = []
    for nid in node_ids:
        n = layout.find(nid)
        if n:
            rects.append(n.rect)
    if not rects:
        return None
    min_x = min(r.x for r in rects)
    min_y = min(r.y for r in rects)
    max_x = max(r.x2 for r in rects)
    max_y = max(r.y2 for r in rects)
    return Rect(min_x, min_y, max_x - min_x, max_y - min_y)


def _render_ann_box(
    g: dw.Group,
    ann: AnnotationBox,
    layout: SolvedLayout,
    ox: float, oy: float,
    dark: bool,
) -> None:
    pad = 10
    br = _nodes_bounding_rect(ann.nodes, layout)
    if br is None:
        return
    x, y = br.x + ox - pad, br.y + oy - pad
    w, h = br.w + pad * 2, br.h + pad * 2
    color = ann.color or ("#888888" if dark else "#666666")
    dash = "6,4" if ann.style == "dashed" else ""
    rect_kwargs: dict = dict(
        fill="none",
        stroke=color,
        stroke_width=1,
        rx=6, ry=6,
    )
    if dash:
        rect_kwargs["stroke_dasharray"] = dash
    g.append(dw.Rectangle(x, y, w, h, **rect_kwargs))
    if ann.label:
        lx = x + w / 2
        ly = y - 6
        label_bg = "#1E1E2E" if dark else "#FFFFFF"
        lw_px = len(ann.label) * 7
        g.append(dw.Rectangle(lx - lw_px / 2 - 4, ly - 10,
                               lw_px + 8, 14,
                               fill=label_bg, stroke="none"))
        g.append(dw.Text(
            ann.label, 11, lx, ly,
            font_family=ANNOTATION_FONT,
            fill=color,
            text_anchor="middle",
            dominant_baseline="auto",
        ))


def _render_ann_callout(
    g: dw.Group,
    ann: AnnotationCallout,
    layout: SolvedLayout,
    ox: float, oy: float,
    dark: bool,
) -> None:
    n = layout.find(ann.anchor)
    if n is None:
        return
    r = n.rect
    color = "#555555" if not dark else "#AAAAAA"
    offsets = {
        "above": (r.cx + ox, r.y + oy - 16),
        "below": (r.cx + ox, r.y2 + oy + 16),
        "left":  (r.x + ox - 8, r.cy + oy),
        "right": (r.x2 + ox + 8, r.cy + oy),
    }
    tx, ty = offsets.get(ann.position, offsets["above"])
    g.append(dw.Text(
        ann.text, 11, tx, ty,
        font_family=ANNOTATION_FONT,
        fill=color,
        text_anchor="middle",
        dominant_baseline="auto",
    ))


def _render_ann_separator(
    g: dw.Group,
    ann: AnnotationSeparator,
    layout: SolvedLayout,
    ox: float, oy: float,
    dark: bool,
) -> None:
    if len(ann.between) < 2:
        return
    a = layout.find(ann.between[0])
    b = layout.find(ann.between[-1])
    if a is None or b is None:
        return
    # Draw a vertical dashed line between the two nodes.
    x = (a.rect.x2 + b.rect.x) / 2 + ox
    min_y = min(a.rect.y, b.rect.y) + oy - 10
    max_y = max(a.rect.y2, b.rect.y2) + oy + 10
    color = "#888888" if dark else "#AAAAAA"
    g.append(dw.Line(x, min_y, x, max_y,
                     stroke=color, stroke_width=1,
                     stroke_dasharray="6,4"))
    if ann.label:
        g.append(dw.Text(
            ann.label, 10, x + 4, (min_y + max_y) / 2,
            font_family=ANNOTATION_FONT,
            fill=color,
            dominant_baseline="central",
        ))


def _render_ann_badge(
    g: dw.Group,
    ann: AnnotationBadge,
    layout: SolvedLayout,
    ox: float, oy: float,
    dark: bool,
) -> None:
    n = layout.find(ann.anchor)
    if n is None:
        return
    r = n.rect
    color = "#555555" if not dark else "#AAAAAA"
    g.append(dw.Text(
        ann.text, 10,
        r.x + ox + 6, r.y + oy + 10,
        font_family=ANNOTATION_FONT,
        fill=color,
        dominant_baseline="central",
    ))


# ---------------------------------------------------------------------------
# Convenience: render both modes
# ---------------------------------------------------------------------------

def render_both(
    routed: RoutedLayout,
    model: Model,
    view: DiagramView,
) -> tuple[str, str]:
    """Return (light_svg, dark_svg)."""
    light = render(routed, model, view, dark=False)
    dark  = render(routed, model, view, dark=True)
    return light, dark
