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

def _seg_intersect_horiz(
    px1: float, py1: float, px2: float, py2: float,
    lx: float, rx: float, y: float,
) -> float | None:
    """X coordinate where segment (p1→p2) crosses horizontal line y, within [lx,rx], or None."""
    dy = py2 - py1
    if abs(dy) < 1e-6:
        return None
    t = (y - py1) / dy
    if not (0.0 < t < 1.0):
        return None
    x = px1 + t * (px2 - px1)
    if lx <= x <= rx:
        return x
    return None


def _seg_intersect_vert(
    px1: float, py1: float, px2: float, py2: float,
    ty: float, by: float, x: float,
) -> float | None:
    """Y coordinate where segment (p1→p2) crosses vertical line x, within [ty,by], or None."""
    dx = px2 - px1
    if abs(dx) < 1e-6:
        return None
    t = (x - px1) / dx
    if not (0.0 < t < 1.0):
        return None
    y = py1 + t * (py2 - py1)
    if ty <= y <= by:
        return y
    return None


# Gap half-width to cut into a box border where an edge crosses it.
BORDER_GAP = 6  # px each side of the crossing point


def _compute_border_gaps(
    nodes: list,
    edges: list,
    ox: float, oy: float,
) -> dict:
    """Return {node_id: {'top': [x,...], 'bottom': [x,...], 'left': [y,...], 'right': [y,...]}}."""
    gaps: dict = {}

    # Build a flat dict of node rects (in SVG coords).
    rects: dict = {}
    def collect(ns):
        for n in ns:
            r = n.rect
            rects[n.id] = (r.x + ox, r.y + oy, r.w, r.h)
            if n.children:
                collect(n.children)
    collect(nodes)

    for edge in edges:
        pts = [(p.x + ox, p.y + oy) for p in edge.points]
        for nid, (nx, ny, nw, nh) in rects.items():
            for i in range(len(pts) - 1):
                x1, y1 = pts[i]
                x2, y2 = pts[i+1]
                g = gaps.setdefault(nid, {'top': [], 'bottom': [], 'left': [], 'right': []})
                # Top edge
                cx = _seg_intersect_horiz(x1, y1, x2, y2, nx, nx+nw, ny)
                if cx is not None:
                    g['top'].append(cx)
                # Bottom edge
                cx = _seg_intersect_horiz(x1, y1, x2, y2, nx, nx+nw, ny+nh)
                if cx is not None:
                    g['bottom'].append(cx)
                # Left edge
                cy = _seg_intersect_vert(x1, y1, x2, y2, ny, ny+nh, nx)
                if cy is not None:
                    g['left'].append(cy)
                # Right edge
                cy = _seg_intersect_vert(x1, y1, x2, y2, ny, ny+nh, nx+nw)
                if cy is not None:
                    g['right'].append(cy)
    return gaps


def _draw_side_with_gaps(
    g: dw.Group,
    pts: list[tuple[float,float]],
    crossings: list[float],
    stroke: str,
    stroke_width: float,
    stroke_dash: str,
    gap: float = BORDER_GAP,
) -> None:
    """Draw a straight line from pts[0] to pts[-1] as segments, skipping gaps at crossings.

    pts must be a two-point list defining a horizontal or vertical line.
    crossings are the coordinates (x for horiz, y for vert) where gaps are cut.
    """
    x0, y0 = pts[0]
    x1, y1 = pts[1]
    horiz = abs(y1 - y0) < 1e-6
    # Parameter is x for horizontal, y for vertical.
    start = x0 if horiz else y0
    end   = x1 if horiz else y1
    if start > end:
        start, end = end, start

    # Build gap intervals and sort.
    intervals = sorted((max(c - gap, start), min(c + gap, end)) for c in crossings)
    # Merge overlapping intervals.
    merged: list[tuple[float,float]] = []
    for lo, hi in intervals:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append([lo, hi])

    kwargs: dict = dict(stroke=stroke, stroke_width=stroke_width, fill="none")
    if stroke_dash:
        kwargs["stroke_dasharray"] = stroke_dash

    # Draw segments between gaps.
    cursor = start
    for lo, hi in merged:
        if cursor < lo:
            if horiz:
                g.append(dw.Line(cursor, y0, lo, y0, **kwargs))
            else:
                g.append(dw.Line(x0, cursor, x0, lo, **kwargs))
        cursor = hi
    if cursor < end:
        if horiz:
            g.append(dw.Line(cursor, y0, end, y0, **kwargs))
        else:
            g.append(dw.Line(x0, cursor, x0, end, **kwargs))


# Legend sizing constants — kept here so render() can use them before drawing.
_LEGEND_W   = 200
_LEGEND_PAD = 10
_LEGEND_ROW = 22
_LEGEND_GAP = 16   # px gap between diagram edge and legend box


def _legend_items(
    layout: SolvedLayout,
    edges: list,
) -> tuple[list[str], list[str]]:
    """Return (node_types, edge_types) actually present in the view."""
    seen_node: list[str] = []
    def _collect(nodes):
        for n in nodes:
            if n.type not in seen_node and n.type not in ("default",):
                seen_node.append(n.type)
            _collect(n.children)
    _collect(layout.nodes)
    seen_edge: list[str] = []
    for e in edges:
        if e.edge_type not in seen_edge and e.edge_type != "default":
            seen_edge.append(e.edge_type)
    return seen_node, seen_edge


def _legend_dims(node_types: list[str], edge_types: list[str]) -> tuple[float, float]:
    rows = len(node_types) + len(edge_types)
    return _LEGEND_W, _LEGEND_PAD * 2 + rows * _LEGEND_ROW


def render(
    routed: RoutedLayout,
    model: Model,
    view: DiagramView,
    dark: bool = False,
    skip_legend: bool = False,
) -> str:
    """Render a RoutedLayout to an SVG string.

    skip_legend: when True, AnnotationLegend annotations are omitted from the
    SVG and no gutter is reserved.  Used by the Sphinx extension, which renders
    the legend as HTML below the image instead.
    """
    preset = get_preset(model.style.extends)
    node_styles = resolve_style(model.style, dark=dark)

    layout = routed.layout
    bounds = layout.bounds

    # Detect legend annotations and reserve gutter space (unless suppressed).
    legend_anns = [a for a in view.annotations if isinstance(a, AnnotationLegend)]
    right_extra = left_extra = top_extra = bottom_extra = 0.0
    if not skip_legend:
        for ann in legend_anns:
            node_types, edge_types = _legend_items(layout, routed.edges)
            if not node_types and not edge_types:
                continue
            lw, lh = _legend_dims(node_types, edge_types)
            gutter = lw + _LEGEND_GAP * 2
            if ann.position in ("top-right", "bottom-right"):
                right_extra = max(right_extra, gutter)
            else:
                left_extra = max(left_extra, gutter)

    vw = bounds.w + MARGIN * 2 + right_extra + left_extra
    vh = bounds.h + MARGIN * 2 + top_extra + bottom_extra
    ox = MARGIN - bounds.x + left_extra
    oy = MARGIN - bounds.y + top_extra

    # Expand canvas so annotation boxes that extend beyond node bounds are not clipped.
    for ann in view.annotations:
        if not isinstance(ann, AnnotationBox):
            continue
        br = _nodes_bounding_rect(ann.nodes, layout)
        if br is None:
            continue
        pad = ann.padding if hasattr(ann, 'padding') else 10
        pos = ann.label_position if hasattr(ann, 'label_position') else 'top'
        LABEL_H = 26
        pt = (ann.padding_top    if hasattr(ann, 'padding_top')    and ann.padding_top    is not None else pad)
        pr = (ann.padding_right  if hasattr(ann, 'padding_right')  and ann.padding_right  is not None else pad)
        pb = (ann.padding_bottom if hasattr(ann, 'padding_bottom') and ann.padding_bottom is not None else pad)
        pl = (ann.padding_left   if hasattr(ann, 'padding_left')   and ann.padding_left   is not None else pad)
        if pos == 'inside-bottom': pb += LABEL_H
        if pos == 'inside-top':    pt += LABEL_H
        box_x1 = br.x - pl
        box_y1 = br.y - pt
        box_x2 = br.x + br.w + pr
        box_y2 = br.y + br.h + pb
        # Convert to SVG space and check overflow.
        svg_x1 = box_x1 + ox
        svg_y1 = box_y1 + oy
        svg_x2 = box_x2 + ox
        svg_y2 = box_y2 + oy
        if svg_x1 < 0:
            expand = -svg_x1
            ox += expand; vw += expand
        if svg_y1 < 0:
            expand = -svg_y1
            oy += expand; vh += expand
        if svg_x2 > vw:
            vw = svg_x2 + MARGIN
        if svg_y2 > vh:
            vh = svg_y2 + MARGIN

    bg = "#1E1E2E" if dark else "#FFFFFF"
    drawing = dw.Drawing(vw, vh, origin=(0, 0))
    drawing.append(dw.Rectangle(0, 0, vw, vh, fill=bg))
    _add_arrowhead_defs(drawing, dark, preset)

    border_gaps = _compute_border_gaps(layout.nodes, routed.edges, ox, oy)

    nodes_g = dw.Group(id="ggarch-nodes")
    edges_g = dw.Group(id="ggarch-edges")
    ann_g   = dw.Group(id="ggarch-annotations")
    _render_nodes(nodes_g, layout.nodes, node_styles, ox, oy, view, dark, border_gaps)

    for edge in routed.edges:
        _render_edge(edges_g, edge, preset, dark, ox, oy)

    for ann in view.annotations:
        if skip_legend and isinstance(ann, AnnotationLegend):
            continue
        _render_annotation(ann_g, ann, layout, ox, oy, dark, preset, node_styles,
                           routed.edges, vw=vw, vh=vh)

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
    border_gaps: dict | None = None,
) -> None:
    border_gaps = border_gaps or {}
    for node in nodes:
        if node.children:
            _render_node(g, node, node_styles, ox, oy, view, dark, border_gaps)
    for node in nodes:
        if not node.children:
            _render_node(g, node, node_styles, ox, oy, view, dark, border_gaps)


def _render_node(
    g: dw.Group,
    node: SolvedNode,
    node_styles: dict[str, NodeStyle],
    ox: float,
    oy: float,
    view: DiagramView,
    dark: bool = False,
    border_gaps: dict | None = None,
) -> None:
    style = node_styles.get(node.type, node_styles.get("default", NodeStyle()))
    r = node.rect
    x, y, w, h = r.x + ox, r.y + oy, r.w, r.h
    has_children = bool(node.children)
    if node.url:
        escaped = node.url.replace("&", "&amp;").replace('"', "&quot;")
        g.append(dw.Raw(f'<a href="{escaped}" target="_blank">'))
        _render_node_content(g, node, node_styles, ox, oy, view, dark,
                             style, x, y, w, h, has_children, border_gaps)
        g.append(dw.Raw("</a>"))
    else:
        _render_node_content(g, node, node_styles, ox, oy, view, dark,
                             style, x, y, w, h, has_children, border_gaps)


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
    border_gaps: dict | None = None,
) -> None:
    """Render the visual content of a node (shape, children, badge) into g."""
    node_gaps = (border_gaps or {}).get(node.id, {})
    if node.fields and node.type in ("record", "class"):
        _render_structured_node(g, node, style, x, y, w, h, dark)
    elif style.shape == "person":
        _render_person(g, x, y, w, h, style, node.label)
    elif style.shape == "cylinder":
        _render_cylinder(g, x, y, w, h, style, node.label)
    else:
        _render_box(g, x, y, w, h, style, node.label, node.lifecycle,
                    is_container=has_children, border_gaps=node_gaps)
    if node.children:
        _render_nodes(g, node.children, node_styles, ox, oy, view, dark, border_gaps)
    if node.cardinality:
        _render_cardinality_badge(g, x + w - 4, y + 4, node.cardinality)
    scope = node.properties.get("scope", "")
    if scope:
        _render_scope_chip(g, x, y, w, h, scope, dark)


def _lifecycle_stroke_dash(lifecycle: str) -> str:
    return {"init": "6,3", "ephemeral": "2,2"}.get(lifecycle, "")


def _render_box(
    g: dw.Group,
    x: float, y: float, w: float, h: float,
    style: NodeStyle,
    label: str,
    lifecycle: str = "persistent",
    is_container: bool = False,
    border_gaps: dict | None = None,
) -> None:
    from ggarch.layout import CONTAINER_PAD_TOP
    fill        = style.fill if style.fill != "none" else "none"
    stroke      = style.stroke
    stroke_dash = style.stroke_dash or _lifecycle_stroke_dash(lifecycle)
    stroke_width = style.stroke_width
    r           = style.border_radius

    node_gaps = border_gaps or {}
    has_gaps = any(node_gaps.get(face) for face in ('top', 'bottom', 'left', 'right'))

    if has_gaps:
        # Draw fill rect (no stroke), then each side as separate segments with gaps.
        if fill != "none":
            g.append(dw.Rectangle(x, y, w, h, fill=fill, stroke="none", rx=r, ry=r))
        for face, pts, crossings in (
            ('top',    [(x, y),     (x+w, y)],   node_gaps.get('top',    [])),
            ('bottom', [(x, y+h),   (x+w, y+h)], node_gaps.get('bottom', [])),
            ('left',   [(x, y),     (x, y+h)],   node_gaps.get('left',   [])),
            ('right',  [(x+w, y),   (x+w, y+h)], node_gaps.get('right',  [])),
        ):
            _draw_side_with_gaps(g, pts, crossings, stroke, stroke_width, stroke_dash)
    else:
        rect_kwargs: dict = dict(
            fill=fill, stroke=stroke,
            stroke_width=stroke_width, rx=r, ry=r,
        )
        if stroke_dash:
            rect_kwargs["stroke_dasharray"] = stroke_dash
        g.append(dw.Rectangle(x, y, w, h, **rect_kwargs))

    if is_container:
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


def _render_person(
    g: dw.Group,
    x: float, y: float, w: float, h: float,
    style: NodeStyle,
    label: str,
) -> None:
    """Person node: rounded rect with a small person icon in the top-left corner.

    The icon is small enough to leave the label area unobstructed regardless
    of node height. Same bounding-box and stroke-weight convention as all
    other shapes.
    """
    fill   = style.fill if style.fill != "none" else "#F0F0F0"
    stroke = style.stroke
    sw     = style.stroke_width
    r      = style.border_radius

    # Bounding rect.
    g.append(dw.Rectangle(x, y, w, h,
                          fill=fill, stroke=stroke, stroke_width=sw,
                          rx=r, ry=r))

    # Small person icon: head + shoulders, confined to top-left ~14x14px.
    icon_size = min(h * 0.38, 14)
    ix = x + 5
    iy = y + 4
    head_r = icon_size * 0.28
    head_cx = ix + icon_size * 0.40
    head_cy = iy + head_r
    g.append(dw.Circle(head_cx, head_cy, head_r,
                       fill=stroke, stroke="none"))
    shoulder_cy = head_cy + head_r + icon_size * 0.12
    srx = icon_size * 0.40
    sry = icon_size * 0.22
    g.append(dw.Path(
        d=(f"M {head_cx - srx:.1f} {shoulder_cy:.1f} "
           f"A {srx:.1f} {sry:.1f} 0 0 1 "
           f"{head_cx + srx:.1f} {shoulder_cy:.1f} Z"),
        fill=stroke, stroke="none",
    ))

    # Label centred in the box.
    _render_label(g, x + w / 2, y + h / 2, label, style)


def _render_cylinder(
    g: dw.Group,
    x: float, y: float, w: float, h: float,
    style: NodeStyle,
    label: str,
) -> None:
    """Database cylinder: rect body with shallow elliptical caps.

    Cap depth is kept small (8px max) so it reads as a subtle type indicator
    at the same visual weight as a rounded-rect border, not as a competing shape.
    """
    ry   = min(h * 0.10, 8)   # shallow caps
    fill   = style.fill if style.fill != "none" else "none"
    stroke = style.stroke
    sw     = style.stroke_width

    # Body: rect from top-cap-centre to bottom-cap-centre.
    g.append(dw.Rectangle(x, y + ry, w, h - ry * 2,
                          fill=fill, stroke="none"))
    # Side strokes only (left and right verticals).
    g.append(dw.Line(x, y + ry, x, y + h - ry,
                     stroke=stroke, stroke_width=sw))
    g.append(dw.Line(x + w, y + ry, x + w, y + h - ry,
                     stroke=stroke, stroke_width=sw))
    # Bottom cap.
    g.append(dw.Ellipse(x + w / 2, y + h - ry, w / 2, ry,
                        fill=fill, stroke=stroke, stroke_width=sw))
    # Top cap (drawn last to cover the body rect top edge).
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
# Scope chip
# ---------------------------------------------------------------------------

# Small palette of distinguishable colors for scope chips.
# Chosen to be readable against both light and dark backgrounds.
_SCOPE_PALETTE_LIGHT = [
    "#4A90D9",  # blue
    "#7B68EE",  # medium slate blue
    "#2ECC71",  # emerald
    "#E67E22",  # carrot orange (distinct from Juju orange)
    "#E91E8C",  # pink
    "#00BCD4",  # cyan
    "#8BC34A",  # light green
    "#FF5722",  # deep orange
]
_SCOPE_PALETTE_DARK = [
    "#74AADC",
    "#9F8FEF",
    "#58D68D",
    "#F0A060",
    "#F06AAE",
    "#40D8EC",
    "#A8D470",
    "#FF8A65",
]


def _scope_color(scope: str, dark: bool = False) -> str:
    """Derive a stable color for a scope string from the palette."""
    palette = _SCOPE_PALETTE_DARK if dark else _SCOPE_PALETTE_LIGHT
    idx = hash(scope) % len(palette)
    return palette[idx]


def _render_scope_chip(
    g: dw.Group,
    x: float, y: float, w: float, h: float,
    scope: str,
    dark: bool = False,
) -> None:
    """Render a small colored scope pill at the bottom-right of a node."""
    color = _scope_color(scope, dark)
    # Pill dimensions: small, fixed size.
    ph, pw = 7, min(len(scope) * 4.5 + 6, w * 0.7)
    px = x + w - pw - 3
    py = y + h - ph - 3
    g.append(dw.Rectangle(px, py, pw, ph,
                           fill=color, stroke="none", rx=3, ry=3))
    g.append(dw.Text(scope, 6, px + pw / 2, py + ph / 2,
                     font_family=LABEL_FONT,
                     fill="#FFFFFF",
                     text_anchor="middle",
                     dominant_baseline="central"))


# ---------------------------------------------------------------------------
# Edge rendering
# ---------------------------------------------------------------------------

def _point_along_path(pts: list[tuple[float,float]], dist: float) -> tuple[float,float]:
    """Return the point at `dist` px along the polyline pts."""
    remaining = dist
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i+1]
        seg = math.hypot(x1 - x0, y1 - y0)
        if remaining <= seg or i == len(pts) - 2:
            t = remaining / seg if seg > 0 else 0
            return (x0 + t * (x1 - x0), y0 + t * (y1 - y0))
        remaining -= seg
    return pts[-1]


def _pts_before_dist(pts: list[tuple[float,float]], dist: float) -> list[tuple[float,float]]:
    """Return the sub-polyline from pts[0] up to the point at `dist` along the path."""
    result = [pts[0]]
    remaining = dist
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i+1]
        seg = math.hypot(x1 - x0, y1 - y0)
        if remaining <= seg or i == len(pts) - 2:
            t = remaining / seg if seg > 0 else 0
            result.append((x0 + t * (x1 - x0), y0 + t * (y1 - y0)))
            return result
        result.append((x1, y1))
        remaining -= seg
    return result


def _pts_after_dist(pts: list[tuple[float,float]], dist: float) -> list[tuple[float,float]]:
    """Return the sub-polyline from the point at `dist` along the path to pts[-1]."""
    remaining = dist
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i+1]
        seg = math.hypot(x1 - x0, y1 - y0)
        if remaining <= seg or i == len(pts) - 2:
            t = remaining / seg if seg > 0 else 0
            start = (x0 + t * (x1 - x0), y0 + t * (y1 - y0))
            return [start] + list(pts[i+1:])
        remaining -= seg
    return [pts[-1]]


def _path_d(pts: list[tuple[float,float]]) -> str:
    d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"
    for x, y in pts[1:]:
        d += f" L {x:.1f} {y:.1f}"
    return d


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

    path_kwargs: dict = dict(
        fill="none",
        stroke=es.stroke,
        stroke_width=es.stroke_width,
    )
    if edge.style == "dashed" or es.stroke_dash:
        path_kwargs["stroke_dasharray"] = es.stroke_dash or "6,3"
    elif edge.style == "dotted":
        path_kwargs["stroke_dasharray"] = "2,2"

    if not edge.label:
        # No label: single path with arrowhead.
        if edge.arrow in ("forward", "both"):
            path_kwargs["marker_end"] = "url(#arrow)"
        if edge.arrow in ("back", "both"):
            path_kwargs["marker_start"] = "url(#arrow)"
        g.append(dw.Path(d=_path_d(pts), **path_kwargs))
        return

    # ---- Labelled edge: gap interrupt or perpendicular offset ----
    path_len = sum(
        math.hypot(pts[i+1][0] - pts[i][0], pts[i+1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    )
    font_size  = 9
    char_w     = 5.5   # px — must match solver _LABEL_CHAR_W to avoid gap/text mismatch
    PADDING    = 0     # px each side of gap — char_w overestimate provides implicit clearance
    MIN_TAIL   = 16    # px of visible arrow on each side of gap (shaft beyond arrowhead)
    PERP_OFFSET = 9   # px perpendicular shift in offset mode

    # Identify the longest segment — the label lives there.
    seg_lens = [
        math.hypot(pts[i+1][0] - pts[i][0], pts[i+1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    ]
    longest_i      = seg_lens.index(max(seg_lens))
    seg_start_dist = sum(seg_lens[:longest_i])
    seg_end_dist   = seg_start_dist + seg_lens[longest_i]
    mid_dist       = (seg_start_dist + seg_end_dist) / 2

    # Direction of the longest segment.
    sx0, sy0 = pts[longest_i]
    sx1, sy1 = pts[longest_i + 1]
    seg_dx = sx1 - sx0; seg_dy = sy1 - sy0
    seg_len = seg_lens[longest_i]
    ux = abs(seg_dx / seg_len) if seg_len > 0 else 1.0
    uy = abs(seg_dy / seg_len) if seg_len > 0 else 0.0
    # Unit perpendicular — points "above" the arrow (CW rotation, used in offset mode).
    # SVG y increases downward, so "above" = negative y for rightward arrows.
    px =  seg_dy / seg_len if seg_len > 0 else 0.0
    py = -seg_dx / seg_len if seg_len > 0 else -1.0

    # Wrap label using the longest segment as the budget (not total path).
    max_chars = max(int(seg_lens[longest_i] / char_w), 1)
    raw_lines = edge.label.split("\\n")
    wrapped: list[str] = []
    for raw in raw_lines:
        words = raw.split()
        if not words:
            wrapped.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            if len(cur) + 1 + len(w) <= max_chars:
                cur += " " + w
            else:
                wrapped.append(cur)
                cur = w
        wrapped.append(cur)

    max_line_w = max(len(l) for l in wrapped) * char_w
    lh = font_size * 1.5
    text_h = lh * len(wrapped)

    # Gap size = width of the label along the arrow direction.
    # The label is always rendered horizontally (not rotated), so for an arrow
    # at angle θ the gap along the arrow that clears the label is:
    #   max_line_w / ux   (when the arrow is mostly horizontal)
    #   text_h / uy       (when mostly vertical)
    # We take the larger of the two non-degenerate projections so the label
    # always clears the line, then add padding.
    if ux >= uy:
        # Mostly horizontal — gap driven by label width.
        gap_needed = max_line_w / ux if ux > 0.1 else max_line_w
    else:
        # Mostly vertical — gap driven by label height.
        gap_needed = text_h / uy if uy > 0.1 else text_h

    min_seg_for_gap = gap_needed + PADDING * 2 + MIN_TAIL * 2
    use_gap = seg_lens[longest_i] >= min_seg_for_gap

    lm = _point_along_path(pts, mid_dist)
    mx, my = lm[0], lm[1]

    if use_gap:
        max_gap = seg_lens[longest_i] - MIN_TAIL * 2
        gap = min(gap_needed + PADDING * 2, max_gap)
        half_gap = gap / 2
        gap_start_dist = max(mid_dist - half_gap, seg_start_dist + MIN_TAIL)
        gap_end_dist   = min(mid_dist + half_gap, seg_end_dist   - MIN_TAIL)

        kw1 = dict(path_kwargs)
        if edge.arrow in ("back", "both"):
            kw1["marker_start"] = "url(#arrow)"
        pre_pts = _pts_before_dist(pts, gap_start_dist)
        if len(pre_pts) >= 2:
            g.append(dw.Path(d=_path_d(pre_pts), **kw1))

        kw2 = dict(path_kwargs)
        if edge.arrow in ("forward", "both"):
            kw2["marker_end"] = "url(#arrow)"
        post_pts = _pts_after_dist(pts, gap_end_dist)
        if len(post_pts) >= 2:
            g.append(dw.Path(d=_path_d(post_pts), **kw2))
    else:
        # Offset mode: draw path whole, float label perpendicularly.
        kw = dict(path_kwargs)
        if edge.arrow in ("forward", "both"):
            kw["marker_end"] = "url(#arrow)"
        if edge.arrow in ("back", "both"):
            kw["marker_start"] = "url(#arrow)"
        g.append(dw.Path(d=_path_d(pts), **kw))
        mx += px * PERP_OFFSET
        my += py * PERP_OFFSET

    # Render label text.
    total_h = lh * len(wrapped)
    start_y = my - total_h / 2 + lh * 0.5
    for i, line in enumerate(wrapped):
        g.append(dw.Text(
            line, font_size, mx, start_y + i * lh,
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
    edges: list | None = None,
    vw: float = 0,
    vh: float = 0,
) -> None:
    if isinstance(ann, AnnotationBox):
        _render_ann_box(g, ann, layout, ox, oy, dark, edges or [])
    elif isinstance(ann, AnnotationCallout):
        _render_ann_callout(g, ann, layout, ox, oy, dark)
    elif isinstance(ann, AnnotationSeparator):
        _render_ann_separator(g, ann, layout, ox, oy, dark)
    elif isinstance(ann, AnnotationBadge):
        _render_ann_badge(g, ann, layout, ox, oy, dark)
    elif isinstance(ann, AnnotationLegend):
        if preset is not None and node_styles is not None:
            _render_ann_legend(g, ann, layout, ox, oy, dark, preset, node_styles,
                               edges or [], vw=vw, vh=vh)


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
    edges: list | None = None,
) -> None:
    pad   = ann.padding if hasattr(ann, 'padding') else 10
    pt    = (ann.padding_top    if hasattr(ann, 'padding_top')    and ann.padding_top    is not None else pad)
    pr    = (ann.padding_right  if hasattr(ann, 'padding_right')  and ann.padding_right  is not None else pad)
    pb    = (ann.padding_bottom if hasattr(ann, 'padding_bottom') and ann.padding_bottom is not None else pad)
    pl    = (ann.padding_left   if hasattr(ann, 'padding_left')   and ann.padding_left   is not None else pad)
    pos   = ann.label_position if hasattr(ann, 'label_position') else 'top'

    # For inside-* positions, reserve an extra strip for the label.
    LABEL_H = 26
    if pos == 'inside-bottom':
        pb += LABEL_H
    elif pos == 'inside-top':
        pt += LABEL_H

    br = _nodes_bounding_rect(ann.nodes, layout)
    if br is None:
        return
    x = br.x + ox - pl
    y = br.y + oy - pt
    w = br.w + pl + pr
    h = br.h + pt + pb
    color = ann.color or ("#888888" if dark else "#666666")
    dash = "6,4" if ann.style == "dashed" else ""

    # Compute where routed edges cross each side of the annotation box.
    side_gaps: dict[str, list[float]] = {'top': [], 'bottom': [], 'left': [], 'right': []}
    for edge in (edges or []):
        pts = [(p.x + ox, p.y + oy) for p in edge.points]
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]; x2, y2 = pts[i+1]
            cx = _seg_intersect_horiz(x1, y1, x2, y2, x, x+w, y)
            if cx is not None: side_gaps['top'].append(cx)
            cx = _seg_intersect_horiz(x1, y1, x2, y2, x, x+w, y+h)
            if cx is not None: side_gaps['bottom'].append(cx)
            cy = _seg_intersect_vert(x1, y1, x2, y2, y, y+h, x)
            if cy is not None: side_gaps['left'].append(cy)
            cy = _seg_intersect_vert(x1, y1, x2, y2, y, y+h, x+w)
            if cy is not None: side_gaps['right'].append(cy)

    has_gaps = any(side_gaps[f] for f in side_gaps)
    if has_gaps:
        for face, pts2, crossings in (
            ('top',    [(x, y),   (x+w, y)],   side_gaps['top']),
            ('bottom', [(x, y+h), (x+w, y+h)], side_gaps['bottom']),
            ('left',   [(x, y),   (x, y+h)],   side_gaps['left']),
            ('right',  [(x+w, y), (x+w, y+h)], side_gaps['right']),
        ):
            _draw_side_with_gaps(g, pts2, crossings, color, 1, dash)
    else:
        rect_kwargs: dict = dict(fill="none", stroke=color, stroke_width=1, rx=6, ry=6)
        if dash:
            rect_kwargs["stroke_dasharray"] = dash
        g.append(dw.Rectangle(x, y, w, h, **rect_kwargs))

    if ann.label:
        if pos == 'inside-bottom':
            lx, ly, anchor = x + w / 2, y + h - LABEL_H / 2, "middle"
        elif pos == 'inside-top':
            lx, ly, anchor = x + w / 2, y + LABEL_H / 2,     "middle"
        elif pos == 'bottom':
            lx, ly, anchor = x + w / 2, y + h + 14,           "middle"
        elif pos == 'left':
            lx, ly, anchor = x - 14,    y + h / 2,             "end"
        elif pos == 'right':
            lx, ly, anchor = x + w + 14, y + h / 2,            "start"
        else:  # top (default)
            lx, ly, anchor = x + w / 2, y - 14,                "middle"
        g.append(dw.Text(
            ann.label, 11, lx, ly,
            font_family=ANNOTATION_FONT,
            fill=color,
            text_anchor=anchor,
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
    edges: list,
    vw: float = 0,
    vh: float = 0,
) -> None:
    """Render a visual key in the gutter reserved by render()."""
    SWATCH_W = 24
    SWATCH_H = 14
    TEXT_X   = _LEGEND_PAD + SWATCH_W + 8
    bg       = "#1E1E2E" if dark else "#FFFFFF"
    border   = "#555555" if dark else "#CCCCCC"
    text_col = "#CDD6F4" if dark else "#333333"

    seen_node_types, seen_edge_types = _legend_items(layout, edges)
    rows = len(seen_node_types) + len(seen_edge_types)
    if rows == 0:
        return
    lw, lh = _legend_dims(seen_node_types, seen_edge_types)

    # Position in the gutter that render() reserved.
    # Right-side gutters: lx = vw - _LEGEND_GAP - lw
    # Left-side gutters:  lx = _LEGEND_GAP
    # Vertical: top aligns near top margin; bottom aligns near bottom.
    if ann.position in ("top-right", "bottom-right"):
        lx = vw - _LEGEND_GAP - lw
    else:
        lx = _LEGEND_GAP
    if ann.position in ("top-left", "top-right"):
        ly = _LEGEND_GAP
    else:
        ly = vh - _LEGEND_GAP - lh

    # Background box.
    g.append(dw.Rectangle(lx, ly, lw, lh,
                          fill=bg, stroke=border, stroke_width=1, rx=4, ry=4))

    y = ly + _LEGEND_PAD
    # Node type swatches.
    for ntype in seen_node_types:
        style = node_styles.get(ntype, node_styles.get("default", NodeStyle()))
        fill   = style.fill if style.fill != "none" else bg
        stroke = style.stroke
        display = ann.labels.get(ntype, ntype)
        g.append(dw.Rectangle(lx + _LEGEND_PAD, y, SWATCH_W, SWATCH_H,
                              fill=fill, stroke=stroke, stroke_width=1, rx=2, ry=2))
        g.append(dw.Text(display, 10, lx + TEXT_X, y + SWATCH_H / 2,
                         font_family=LABEL_FONT, fill=text_col,
                         dominant_baseline="central"))
        y += _LEGEND_ROW

    # Edge type line samples.
    for etype in seen_edge_types:
        es = preset.edge(etype, dark=dark)
        line_kwargs: dict = dict(stroke=es.stroke, stroke_width=es.stroke_width)
        if es.stroke_dash:
            line_kwargs["stroke_dasharray"] = es.stroke_dash
        display = ann.labels.get(etype, etype)
        mid_y = y + SWATCH_H / 2
        g.append(dw.Line(lx + _LEGEND_PAD, mid_y,
                         lx + _LEGEND_PAD + SWATCH_W, mid_y, **line_kwargs))
        # Arrowhead nub.
        ah = 5
        g.append(dw.Lines(
            lx + _LEGEND_PAD + SWATCH_W - ah, mid_y - ah / 2,
            lx + _LEGEND_PAD + SWATCH_W,      mid_y,
            lx + _LEGEND_PAD + SWATCH_W - ah, mid_y + ah / 2,
            fill=es.stroke, close=False,
            stroke=es.stroke, stroke_width=es.stroke_width,
        ))
        g.append(dw.Text(display, 10, lx + TEXT_X, mid_y,
                         font_family=LABEL_FONT, fill=text_col,
                         dominant_baseline="central"))
        y += _LEGEND_ROW


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
