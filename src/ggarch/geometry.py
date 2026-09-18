"""ggarch shared geometry — labels and strips.

The single source of collision measurement (the ADR-002
``label_geometry`` precedent: one module, imported by the renderer,
solver, router and the geometry audit, never replicated).

Along-path edge labels (ADR-002): a label rides an edge's longest leg
on an SVG textPath, above the line in the text's local frame, one
textPath per wrapped line stacked outward, mirrored on right-to-left
legs — never upside-down, no background mask, the stroke never split.

Strips (ADR-003): every edge occupies a swept corridor — stroke width,
arrowhead caps, and the one-sided label extent. A route is
collision-free only if its whole strip clears every obstacle: node
rects, container walls, and other edges' strips. All strip-vs-rect and
strip-vs-strip intersection semantics live here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

LABEL_FONT      = "'Ubuntu Sans', Ubuntu, system-ui, -apple-system, sans-serif"
ANNOTATION_FONT = LABEL_FONT
ARROWHEAD_SIZE  = 8     # px


# ---------------------------------------------------------------------------
# Along-path edge labels (ADR-002) — shared geometry
# ---------------------------------------------------------------------------

LABEL_FONT_SIZE = 9
LABEL_CHAR_W    = 5.5                    # px per character (width model)
LABEL_LINE_H    = LABEL_FONT_SIZE * 1.5   # px per wrapped line
LABEL_SIDE_PAD  = 8     # px — clearance from endpoint boxes / arrowheads
LABEL_CLEARANCE = 3     # px — stroke-to-text clearance below the descent
LABEL_DESCENT   = LABEL_FONT_SIZE * 0.25  # px — descent below the baseline


@dataclass
class LabelGeometry:
    """Everything the renderer, solver, or audit needs about a label."""
    leg: tuple[float, float, float, float]  # x0, y0, x1, y1 — longest leg
    leg_len: float
    ux: float   # mirror-normalized unit direction of the label path
    uy: float
    up_x: float  # unit "above" in the text's local frame (screen coords)
    up_y: float
    mirror: bool
    rotated: bool  # |uy| > |ux| — the label renders rotated
    lines: list[str]
    max_line_w: float
    widest_word_w: float
    anchor: tuple[float, float]  # anchor point at anchor_frac along the leg
    strip: tuple[float, float, float, float]  # x, y, x2, y2 — text extent


def wrap_label_lines(label: str, max_chars: int) -> list[str]:
    """Greedy word wrap across manual lines. A word longer than
    max_chars keeps its own line (words are never split) — callers
    detect the overflow via LabelGeometry.widest_word_w."""
    wrapped: list[str] = []
    for raw in label.split("\\n"):
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
    return wrapped


def label_geometry(points, label: str, anchor_frac: float = 0.5) -> LabelGeometry:
    """Measure the along-path label an edge with `points` would draw.

    The label rides the longest leg; `anchor_frac` positions its
    centre along that leg. The strip is the one-sided text extent
    above the stroke — the collision currency for strike checks.
    """
    pts = [(float(x), float(y)) for x, y in points]
    seg_lens = [
        math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    ]
    li = max(range(len(seg_lens)), key=lambda i: seg_lens[i])
    x0, y0 = pts[li]
    x1, y1 = pts[li + 1]
    leg_len = seg_lens[li]
    if leg_len < 1:
        # Degenerate leg: a 1px eastward direction so the label still
        # renders instead of dividing by zero.
        x0, y0 = pts[0]
        x1, y1 = x0 + 1.0, y0
        leg_len = 1.0
    ux, uy = (x1 - x0) / leg_len, (y1 - y0) / leg_len
    # Never upside-down: a leg running right-to-left (or bottom-to-top
    # when vertical) carries mirrored text along a reversed path.
    mirror = ux < 0 or (abs(ux) < 1e-9 and uy < 0)
    if mirror:
        ux, uy = -ux, -uy
    # Text-local "above" (SVG y grows downward): quarter turn
    # counter-clockwise from the reading direction.
    up_x, up_y = uy, -ux

    budget = max(leg_len - LABEL_SIDE_PAD * 2, 1.0)
    max_chars = max(int(budget / LABEL_CHAR_W), 1)
    lines = wrap_label_lines(label, max_chars)
    max_line_w = max(len(l) for l in lines) * LABEL_CHAR_W
    widest_word_w = max(
        (len(w) for raw in label.split("\\n") for w in raw.split()),
        default=0,
    ) * LABEL_CHAR_W

    ax = x0 + (x1 - x0) * anchor_frac
    ay = y0 + (y1 - y0) * anchor_frac
    # Text extent: max_line_w centred on the anchor along the leg,
    # stacked `up` from the stroke (clearance cancels the descent: the
    # bottom line's descent sits `clearance` above the stroke, the top
    # line's ascent tops out at clearance + n * line height).
    depth = LABEL_CLEARANCE + LABEL_LINE_H * len(lines)
    half_w = max_line_w / 2
    corners = (
        (ax - ux * half_w, ay - uy * half_w),
        (ax + ux * half_w, ay + uy * half_w),
        (ax + ux * half_w + up_x * depth, ay + uy * half_w + up_y * depth),
        (ax - ux * half_w + up_x * depth, ay - uy * half_w + up_y * depth),
    )
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return LabelGeometry(
        leg=(x0, y0, x1, y1), leg_len=leg_len, ux=ux, uy=uy,
        up_x=up_x, up_y=up_y, mirror=mirror, rotated=abs(uy) > abs(ux),
        lines=lines, max_line_w=max_line_w, widest_word_w=widest_word_w,
        anchor=(ax, ay), strip=(min(xs), min(ys), max(xs), max(ys)),
    )


# ---------------------------------------------------------------------------
# Distance primitives (exact, no sampling)
# ---------------------------------------------------------------------------

Box = tuple[float, float, float, float]  # x, y, x2, y2


def point_box_dist(p, box: Box) -> float:
    """Distance from a point to a filled axis-aligned box (0 inside)."""
    dx = max(box[0] - p[0], 0.0, p[0] - box[2])
    dy = max(box[1] - p[1], 0.0, p[1] - box[3])
    return math.hypot(dx, dy)


def _seg_box_t(a, b, box: Box) -> float | None:
    """Liang-Barsky: t-interval of segment (a->b) inside the box, or None
    if empty. Returns the entry t when the segment crosses the interior."""
    x0, y0, x1, y1 = box
    t_lo, t_hi = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]),
                 (-dy, a[1] - y0), (dy, y1 - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t_hi:
                return None
            t_lo = max(t_lo, r)
        else:
            if r < t_lo:
                return None
            t_hi = min(t_hi, r)
    return t_lo


def seg_box_dist(a, b, box: Box) -> float:
    """Distance between a segment and a filled axis-aligned box (0 on
    contact or interior crossing)."""
    if _seg_box_t(a, b, box) is not None:
        return 0.0
    best = min(point_box_dist(a, box), point_box_dist(b, box))
    x0, y0, x1, y1 = box
    for e in (
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    ):
        d = seg_seg_dist(a, b, e[0], e[1])
        if d < best:
            best = d
    return best


def seg_seg_dist(a, b, c, d) -> float:
    """Distance between two segments (0 on crossing)."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denom = r[0] * s[1] - r[1] * s[0]
    if denom == 0:
        # Parallel (or degenerate): min endpoint-to-segment distance.
        return min(
            _point_seg_dist(a, c, d), _point_seg_dist(b, c, d),
            _point_seg_dist(c, a, b), _point_seg_dist(d, a, b),
        )
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / denom
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return 0.0
    return min(
        _point_seg_dist(a, c, d), _point_seg_dist(b, c, d),
        _point_seg_dist(c, a, b), _point_seg_dist(d, a, b),
    )


def _point_seg_dist(p, a, b) -> float:
    """Distance from point p to segment (a, b)."""
    ab = (b[0] - a[0], b[1] - a[1])
    ap = (p[0] - a[0], p[1] - a[1])
    ab2 = ab[0] * ab[0] + ab[1] * ab[1]
    if ab2 == 0:
        return math.hypot(ap[0], ap[1])
    t = max(0.0, min(1.0, (ap[0] * ab[0] + ap[1] * ab[1]) / ab2))
    return math.hypot(p[0] - (a[0] + ab[0] * t), p[1] - (a[1] + ab[1] * t))


def rects_overlap(a: Box, b: Box, eps: float = 0.5) -> bool:
    """Do two (x, y, x2, y2) boxes overlap by more than eps?"""
    return not (a[2] <= b[0] + eps or b[2] <= a[0] + eps
                or a[3] <= b[1] + eps or b[3] <= a[1] + eps)


# ---------------------------------------------------------------------------
# Strips (ADR-003) — the collision currency
# ---------------------------------------------------------------------------

STRIP_PAD = 2.0   # px clearance folded into the corridor half-width


@dataclass
class Strip:
    """The swept corridor of one routed edge.

    points: the polyline. half_w: stroke half-width + clearance.
    arrow_start / arrow_end: arrowhead cap radii (incl. half_w) at the
    path ends, 0 when un-arrowed. label: the one-sided text extent,
    or None when the edge carries no label. owner: identifying string
    for residual reports.
    """
    points: list[tuple[float, float]]
    half_w: float
    arrow_start: float = 0.0
    arrow_end: float = 0.0
    label: Box | None = None
    owner: str = ""
    pad: float = STRIP_PAD

    # -- vs a filled rect (node rect, container wall) ---------------------
    def hits_rect(self, rect: Box, inflate: float = 0.0) -> bool:
        """Does any part of the strip enter the rect inflated by its
        corridor half-width? Touching the boundary does not count."""
        for i in range(len(self.points) - 1):
            if seg_box_dist(self.points[i], self.points[i + 1],
                            rect) < self.half_w + inflate:
                return True
        if self.label is not None and rects_overlap(self.label, rect):
            return True
        for cap_r, pt in ((self.arrow_start, self.points[0]),
                          (self.arrow_end, self.points[-1])):
            if cap_r > 0 and point_box_dist(pt, rect) < cap_r + inflate:
                return True
        return False

    # -- vs another strip ---------------------------------------------------
    def hits_strip(self, other: "Strip") -> bool:
        """Do the two strips' swept corridors collide anywhere?"""
        a, b = self, other
        # Corridor vs corridor.
        for i in range(len(a.points) - 1):
            for j in range(len(b.points) - 1):
                if seg_seg_dist(a.points[i], a.points[i + 1],
                                b.points[j], b.points[j + 1]) \
                        < a.half_w + b.half_w:
                    return True
        # Corridor vs label extent.
        if a.label is not None:
            for j in range(len(b.points) - 1):
                if seg_box_dist(b.points[j], b.points[j + 1],
                                a.label) < b.half_w:
                    return True
            for cap_r, pt in ((b.arrow_start, b.points[0]),
                              (b.arrow_end, b.points[-1])):
                if cap_r > 0 and point_box_dist(pt, a.label) < cap_r:
                    return True
        if b.label is not None:
            for i in range(len(a.points) - 1):
                if seg_box_dist(a.points[i], a.points[i + 1],
                                b.label) < a.half_w:
                    return True
            for cap_r, pt in ((a.arrow_start, a.points[0]),
                              (a.arrow_end, a.points[-1])):
                if cap_r > 0 and point_box_dist(pt, b.label) < cap_r:
                    return True
        # Label vs label.
        if a.label is not None and b.label is not None \
                and rects_overlap(a.label, b.label):
            return True
        # Arrow caps vs corridor.
        for cap_r, pt in ((a.arrow_start, a.points[0]),
                          (a.arrow_end, a.points[-1])):
            if cap_r <= 0:
                continue
            for j in range(len(b.points) - 1):
                if _point_seg_dist(pt, b.points[j], b.points[j + 1]) \
                        < cap_r + b.half_w:
                    return True
        for cap_r, pt in ((b.arrow_start, b.points[0]),
                          (b.arrow_end, b.points[-1])):
            if cap_r <= 0:
                continue
            for i in range(len(a.points) - 1):
                if _point_seg_dist(pt, a.points[i], a.points[i + 1]) \
                        < cap_r + a.half_w:
                    return True
        # Cap vs cap.
        for cap_a, pa in ((a.arrow_start, a.points[0]),
                          (a.arrow_end, a.points[-1])):
            if cap_a <= 0:
                continue
            for cap_b, pb in ((b.arrow_start, b.points[0]),
                              (b.arrow_end, b.points[-1])):
                if cap_b <= 0:
                    continue
                if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) \
                        < cap_a + cap_b:
                    return True
        return False


def strips_overlap(a: Strip, b: Strip) -> bool:
    """Convenience wrapper — do two strips collide?"""
    return a.hits_strip(b)


def strip_for_edge(
    points,
    stroke_width: float,
    arrow: str = "forward",
    label_text: str = "",
    anchor_frac: float = 0.5,
    owner: str = "",
) -> Strip:
    """Build the strip a routed edge sweeps.

    The label extent is measured by label_geometry on the longest leg
    (the placement the renderer draws); the corridor is the stroke
    half-width plus STRIP_PAD clearance; arrowheads sweep caps of
    ARROWHEAD_SIZE/2 beyond the corridor at each arrowed end.
    """
    pts = [(float(x), float(y)) for x, y in points]
    half_w = stroke_width / 2 + STRIP_PAD
    cap = ARROWHEAD_SIZE / 2 + half_w
    label = None
    if label_text:
        lg = label_geometry(pts, label_text, anchor_frac)
        label = lg.strip
    return Strip(
        points=pts,
        half_w=half_w,
        arrow_start=cap if arrow in ("back", "both") else 0.0,
        arrow_end=cap if arrow in ("forward", "both") else 0.0,
        label=label,
        owner=owner,
    )


def segment_crosses_rect_interior(
    a, b, rect: Box, eps: float = 0.5,
) -> bool:
    """Does segment (a->b) pass through the rect's interior (inset by
    eps)? The audit's crossing semantics — borrowed, not replicated."""
    inner = (rect[0] + eps, rect[1] + eps, rect[2] - eps, rect[3] - eps)
    return _seg_box_t(a, b, inner) is not None
