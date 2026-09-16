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


def render(
    routed: RoutedLayout,
    model: Model,
    view: DiagramView,
    dark: bool = False,
) -> str:
    """Render a RoutedLayout to an SVG string."""
    preset = get_preset(model.style.extends)
    node_styles = resolve_style(model.style, dark=dark)

    layout = routed.layout
    bounds = layout.bounds

    vw = bounds.w + MARGIN * 2
    vh = bounds.h + MARGIN * 2
    ox = MARGIN - bounds.x
    oy = MARGIN - bounds.y

    bg = "#1E1E2E" if dark else "#FFFFFF"
    drawing = dw.Drawing(vw, vh, origin=(0, 0))
    drawing.append(dw.Rectangle(0, 0, vw, vh, fill=bg))
    _add_arrowhead_defs(drawing, dark, preset)

    # Precompute where edges cross node borders.
    border_gaps = _compute_border_gaps(layout.nodes, routed.edges, ox, oy)

    nodes_g = dw.Group(id="ggarch-nodes")
    edges_g = dw.Group(id="ggarch-edges")
    ann_g   = dw.Group(id="ggarch-annotations")
    _render_nodes(nodes_g, layout.nodes, node_styles, ox, oy, view, dark, border_gaps)

    for edge in routed.edges:
        _render_edge(edges_g, edge, preset, dark, ox, oy)

    for ann in view.annotations:
        _render_annotation(ann_g, ann, layout, ox, oy, dark, preset, node_styles,
                           routed.edges)

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

    # ---- Labelled edge: always split path around label gap ----
    path_len = sum(
        math.hypot(pts[i+1][0] - pts[i][0], pts[i+1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    )
    font_size = 9
    char_w = 5.0
    # Padding on each side of the gap.
    PADDING = 6
    # Wrap label to at most the full path width (no hard clearance floor --
    # let the gap be as small as it needs to be so we always interrupt).
    max_chars = max(int(path_len / char_w), 1)

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

    # Gap = text width + padding on each side; never exceeds 80% of path.
    max_line_w = max(len(l) for l in wrapped) * char_w
    lh = font_size * 1.5
    gap = min(max_line_w + PADDING * 2, path_len * 0.8)
    half_gap = gap / 2
    mid_dist = path_len / 2
    # MIN_TAIL: minimum visible line on each side of the gap before an arrowhead.
    MIN_TAIL = 10
    gap_start_dist = max(mid_dist - half_gap, MIN_TAIL)
    gap_end_dist   = min(mid_dist + half_gap, path_len - MIN_TAIL)
    # If the gap was clamped asymmetrically, re-centre it within the clamped range.
    actual_gap = gap_end_dist - gap_start_dist
    if actual_gap < gap:
        centre = (gap_start_dist + gap_end_dist) / 2
        gap_start_dist = max(centre - half_gap, MIN_TAIL)
        gap_end_dist   = min(centre + half_gap, path_len - MIN_TAIL)
    gap_start = _point_along_path(pts, gap_start_dist)
    gap_end   = _point_along_path(pts, gap_end_dist)

    # First segment with optional back arrowhead.
    kw1 = dict(path_kwargs)
    if edge.arrow in ("back", "both"):
        kw1["marker_start"] = "url(#arrow)"
    g.append(dw.Path(d=_path_d([pts[0], gap_start]), **kw1))

    # Second segment with optional forward arrowhead.
    kw2 = dict(path_kwargs)
    if edge.arrow in ("forward", "both"):
        kw2["marker_end"] = "url(#arrow)"
    g.append(dw.Path(d=_path_d([gap_end, pts[-1]]), **kw2))

    # Label centred on the true path-length midpoint.
    pm = _point_along_path(pts, mid_dist)
    mx, my = pm[0], pm[1]
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
    edges: list | None = None,
) -> None:
    pad = 10
    br = _nodes_bounding_rect(ann.nodes, layout)
    if br is None:
        return
    x, y = br.x + ox - pad, br.y + oy - pad
    w, h = br.w + pad * 2, br.h + pad * 2
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
