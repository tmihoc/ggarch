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
    AnnotationBadge,
    AnnotationBox,
    AnnotationCallout,
    AnnotationLegend,
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
    _render_nodes(nodes_g, layout.nodes, node_styles, ox, oy, view, dark)

    # Render edges.
    for edge in routed.edges:
        _render_edge(edges_g, edge, preset, dark, ox, oy)

    # Render annotations.
    for ann in view.annotations:
        _render_annotation(ann_g, ann, layout, ox, oy, dark, preset, node_styles)

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
    dark: bool = False,
) -> None:
    # Render containers (nodes with children) first so they appear behind.
    for node in nodes:
        if node.children:
            _render_node(g, node, node_styles, ox, oy, view, dark)
    for node in nodes:
        if not node.children:
            _render_node(g, node, node_styles, ox, oy, view, dark)


def _render_node(
    g: dw.Group,
    node: SolvedNode,
    node_styles: dict[str, NodeStyle],
    ox: float,
    oy: float,
    view: DiagramView,
    dark: bool = False,
) -> None:
    style = node_styles.get(node.type, node_styles.get("default", NodeStyle()))
    r = node.rect
    x, y, w, h = r.x + ox, r.y + oy, r.w, r.h
    has_children = bool(node.children)

    # If the node has a url, wrap the visual elements in an SVG <a> element.
    if node.url:
        escaped = node.url.replace("&", "&amp;").replace('"', "&quot;")
        g.append(dw.Raw(f'<a href="{escaped}" target="_blank">'))
        _render_node_content(g, node, node_styles, ox, oy, view, dark,
                             style, x, y, w, h, has_children)
        g.append(dw.Raw("</a>"))
    else:
        _render_node_content(g, node, node_styles, ox, oy, view, dark,
                             style, x, y, w, h, has_children)


def _render_node_content(
    g: dw.Group,
    node: SolvedNode,
    node_styles: dict[str, NodeStyle],
    ox: float,
    oy: float,
    view: DiagramView,
    dark: bool,
    style: NodeStyle,
    x: float,
    y: float,
    w: float,
    h: float,
    has_children: bool,
) -> None:
    """Render the visual content of a node (shape, children, badge) into g."""
    if node.fields and node.type in ("record", "class"):
        _render_structured_node(g, node, style, x, y, w, h, dark)
    elif style.shape == "person":
        _render_person(g, x, y, w, h, style, node.label)
    elif style.shape == "cylinder":
        _render_cylinder(g, x, y, w, h, style, node.label)
    else:
        _render_box(g, x, y, w, h, style, node.label, node.lifecycle,
                    is_container=has_children)
    if node.children:
        _render_nodes(g, node.children, node_styles, ox, oy, view, dark)
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


def _render_structured_node(
    g: dw.Group,
    node: SolvedNode,
    style: NodeStyle,
    x: float, y: float, w: float, h: float,
    dark: bool,
) -> None:
    """Render a record (table) or class (compartment) node with named fields."""
    from ggarch.layout import FIELD_HEADER_H, FIELD_ROW_H

    stroke       = style.stroke
    fill         = style.fill if style.fill != "none" else ("#2A2200" if dark else "#FFFDE7")
    header_fill  = style.stroke  # header uses the stroke colour as background
    font_color   = style.font_color
    row_alt_fill = "#00000010" if not dark else "#FFFFFF08"

    # Outer border.
    g.append(dw.Rectangle(x, y, w, h,
        fill=fill, stroke=stroke, stroke_width=style.stroke_width,
        rx=style.border_radius, ry=style.border_radius,
    ))

    # Header strip.
    g.append(dw.Rectangle(x, y, w, FIELD_HEADER_H,
        fill=header_fill, stroke="none",
        rx=style.border_radius, ry=style.border_radius,
    ))
    # Square off bottom corners of header (overlapping rect).
    if style.border_radius:
        g.append(dw.Rectangle(x, y + FIELD_HEADER_H / 2, w, FIELD_HEADER_H / 2,
            fill=header_fill, stroke="none",
        ))
    # Header label — white text on coloured header.
    header_text = "#FFFFFF" if not dark else "#FFFFFF"
    g.append(dw.Text(
        node.label, FONT_SIZE,
        x + w / 2, y + FIELD_HEADER_H / 2,
        font_family=LABEL_FONT,
        fill=header_text,
        text_anchor="middle",
        dominant_baseline="central",
        font_weight="bold",
    ))

    # Divider line below header.
    g.append(dw.Line(x, y + FIELD_HEADER_H, x + w, y + FIELD_HEADER_H,
        stroke=stroke, stroke_width=1,
    ))

    # Field rows.
    row_text_color = font_color or ("#CDD6F4" if dark else "#333333")
    key_color      = "#E95420"
    type_color     = "#888888" if not dark else "#AAAAAA"

    for i, fld in enumerate(node.fields):
        row_y = y + FIELD_HEADER_H + i * FIELD_ROW_H

        # Alternating row tint.
        if i % 2 == 1:
            g.append(dw.Rectangle(x + 1, row_y, w - 2, FIELD_ROW_H,
                fill=row_alt_fill, stroke="none",
            ))

        # Row divider (skip first).
        if i > 0:
            g.append(dw.Line(x, row_y, x + w, row_y,
                stroke=stroke, stroke_width=0.5, stroke_dasharray="2,2",
            ))

        row_cy = row_y + FIELD_ROW_H / 2
        cursor_x = x + 8

        # Key markers: PK / FK / UK badges.
        if node.type == "record":
            marker = ""
            if fld.pk:  marker = "PK"
            elif fld.fk: marker = "FK"
            elif fld.uk: marker = "UK"
            if marker:
                g.append(dw.Text(
                    marker, 9, cursor_x, row_cy,
                    font_family=LABEL_FONT, fill=key_color,
                    text_anchor="start", dominant_baseline="central",
                    font_weight="bold",
                ))
                cursor_x += 24
        elif node.type == "class":
            # Visibility: pk=public(+), fk=protected(#), uk=private(-)
            vis = "+" if fld.pk else "#" if fld.fk else "-" if fld.uk else " "
            g.append(dw.Text(
                vis, 11, cursor_x, row_cy,
                font_family=LABEL_FONT, fill=key_color,
                text_anchor="start", dominant_baseline="central",
            ))
            cursor_x += 14

        # Field label.
        label_text = fld.label
        if fld.nullable:
            label_text += "?"
        g.append(dw.Text(
            label_text, 11, cursor_x, row_cy,
            font_family=LABEL_FONT, fill=row_text_color,
            text_anchor="start", dominant_baseline="central",
        ))

        # Field type (right-aligned).
        if fld.type:
            g.append(dw.Text(
                fld.type, 10, x + w - 6, row_cy,
                font_family=LABEL_FONT, fill=type_color,
                text_anchor="end", dominant_baseline="central",
                font_style="italic",
            ))


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

    # Edge label: offset perpendicular to the edge direction.
    if edge.label:
        mid = edge.mid
        mx, my = mid.x + ox, mid.y + oy
        dx = edge.end.x - edge.start.x
        dy = edge.end.y - edge.start.y
        length = max(abs(dx) + abs(dy), 1)
        # Perpendicular unit vector (rotate 90° CCW).
        nx, ny = -dy / length, dx / length
        lx = mx + nx * 14
        ly = my + ny * 14
        lines = edge.label.split("\\n")
        lh = es.font_size * 1.4
        total_h = lh * len(lines)
        start_y = ly - total_h / 2 + lh * 0.5
        for i, line in enumerate(lines):
            g.append(dw.Text(
                line, es.font_size, lx, start_y + i * lh,
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
    preset: ResolvedStyle | None = None,
    node_styles: dict | None = None,
) -> None:
    if isinstance(ann, AnnotationBox):
        _render_ann_box(g, ann, layout, ox, oy, dark)
    elif isinstance(ann, AnnotationCallout):
        _render_ann_callout(g, ann, layout, ox, oy, dark)
    elif isinstance(ann, AnnotationSeparator):
        _render_ann_separator(g, ann, layout, ox, oy, dark)
    elif isinstance(ann, AnnotationBadge):
        _render_ann_badge(g, ann, layout, ox, oy, dark)
    elif isinstance(ann, AnnotationLegend):
        if preset is not None and node_styles is not None:
            _render_ann_legend(g, ann, layout, ox, oy, dark, preset, node_styles)


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
        # Label sits inside the box, just below the top border.
        lx = x + w / 2
        ly = y + 14
        g.append(dw.Text(
            ann.label, 11, lx, ly,
            font_family=ANNOTATION_FONT,
            fill=color,
            text_anchor="middle",
            dominant_baseline="central",
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


def _render_ann_legend(
    g: dw.Group,
    ann: AnnotationLegend,
    layout: SolvedLayout,
    ox: float,
    oy: float,
    dark: bool,
    preset: ResolvedStyle,
    node_styles: dict[str, NodeStyle],
) -> None:
    """Render a visual key: node-type colour swatches + edge-type line samples."""
    SWATCH_W = 24
    SWATCH_H = 14
    ROW_H    = 20
    PAD      = 8
    TEXT_X   = PAD + SWATCH_W + 6
    LEGEND_W = 180
    bg       = "#1E1E2E" if dark else "#FFFFFF"
    border   = "#555555" if dark else "#CCCCCC"
    text_col = "#CDD6F4" if dark else "#333333"

    # Collect node types that appear in this layout.
    seen_types: list[str] = []
    def _collect(nodes):
        for n in nodes:
            if n.type not in seen_types and n.type not in ("default",):
                seen_types.append(n.type)
            _collect(n.children)
    _collect(layout.nodes)

    # Collect edge types declared in the preset (skip 'default').
    edge_bank = preset.edge_dark if dark else preset.edge_light
    edge_types = [k for k in edge_bank.keys() if k != "default"]

    rows = len(seen_types) + len(edge_types)
    if rows == 0:
        return
    legend_h = PAD * 2 + rows * ROW_H

    # Position the legend according to ann.position.
    bounds = layout.bounds
    if ann.position == "top-left":
        lx, ly = bounds.x + ox + 4, bounds.y + oy + 4
    elif ann.position == "top-right":
        lx, ly = bounds.x2 + ox - LEGEND_W - 4, bounds.y + oy + 4
    elif ann.position == "bottom-left":
        lx, ly = bounds.x + ox + 4, bounds.y2 + oy - legend_h - 4
    else:  # bottom-right
        lx, ly = bounds.x2 + ox - LEGEND_W - 4, bounds.y2 + oy - legend_h - 4

    # Background box.
    g.append(dw.Rectangle(lx, ly, LEGEND_W, legend_h,
                          fill=bg, stroke=border, stroke_width=1, rx=4, ry=4))

    y = ly + PAD
    # Node type swatches.
    for ntype in seen_types:
        style = node_styles.get(ntype, node_styles.get("default", NodeStyle()))
        fill   = style.fill if style.fill != "none" else bg
        stroke = style.stroke
        g.append(dw.Rectangle(lx + PAD, y, SWATCH_W, SWATCH_H,
                              fill=fill, stroke=stroke, stroke_width=1, rx=2, ry=2))
        g.append(dw.Text(ntype, 10, lx + TEXT_X, y + SWATCH_H / 2,
                         font_family=LABEL_FONT, fill=text_col,
                         dominant_baseline="central"))
        y += ROW_H

    # Edge type line samples.
    for etype in edge_types:
        es = preset.edge(etype, dark=dark)
        line_kwargs: dict = dict(stroke=es.stroke, stroke_width=es.stroke_width)
        if es.stroke_dash:
            line_kwargs["stroke_dasharray"] = es.stroke_dash
        g.append(dw.Line(lx + PAD, y + SWATCH_H / 2,
                         lx + PAD + SWATCH_W, y + SWATCH_H / 2, **line_kwargs))
        g.append(dw.Text(etype, 10, lx + TEXT_X, y + SWATCH_H / 2,
                         font_family=LABEL_FONT, fill=text_col,
                         dominant_baseline="central"))
        y += ROW_H


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
