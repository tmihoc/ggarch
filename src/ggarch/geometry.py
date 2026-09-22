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


def _chord_normal(p0, p1):
    """World perpendicular of the chord p0->p1, unit length:
    (dy, -dx)/len — the convention both the router's bow assignment
    and label_geometry consume (the bow is a signed offset of the
    curve's apex along this normal)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    leg = math.hypot(dx, dy) or 1.0
    return dy / leg, -dx / leg


def _quad_point(p0, p1, normal, bow, t):
    """Point at parameter t on the quadratic bezier P0 -> (bowed
    control) -> P1: the control sits at the chord midpoint displaced
    by 2*bow so the curve passes through midpoint + bow*normal."""
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    cx, cy = mx + normal[0] * 2.0 * bow, my + normal[1] * 2.0 * bow
    s = 1.0 - t
    return (s * s * p0[0] + 2 * t * s * cx + t * t * p1[0],
            s * s * p0[1] + 2 * t * s * cy + t * t * p1[1])


def label_geometry(points, label: str, anchor_frac: float = 0.5,
                   bow: float = 0.0) -> LabelGeometry:
    """Measure the along-path label an edge with `points` would draw.

    The label rides the longest leg; `anchor_frac` positions its
    centre along that leg. The strip is the one-sided text extent
    above the stroke — the collision currency for strike checks.

    `bow` (0.26.2, ADR-009): a signed offset of the drawn curve's apex
    from the chord midpoint, along the chord's world normal. Bowed
    (anti-parallel corridor pairs) labels ride the curve's OUTER side:
    the anchor point is the bezier point at anchor_frac and the depth
    stacks outward, away from the paired stroke."""
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
    # Reading direction follows the arrow (review round 1, the
    # street-name paradigm): vertical legs read along the path
    # direction — a downward arrow's label reads top-to-bottom, an
    # upward one bottom-to-top. Horizontal right-to-left legs keep the
    # LTR mirror: street names always read left-to-right, whatever
    # direction the street runs.
    mirror = ux < 0
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
    if bow:
        # Bowed label: the anchor is the bezier point; the depth stacks
        # OUTWARD (the convex side of the arc — away from the paired
        # stroke), and the strip carries the arc's bulge.
        nx, ny = _chord_normal((x0, y0), (x1, y1))
        ax, ay = _quad_point((x0, y0), (x1, y1), (nx, ny), bow,
                             anchor_frac)
        side = 1.0 if bow > 0 else -1.0
        up_x, up_y = nx * side, ny * side
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
    if bow:
        # The arc bulges past the anchor's corners toward the apex:
        # include the curve's extreme point so the strip covers the
        # drawn stroke's bow.
        nx, ny = _chord_normal((x0, y0), (x1, y1))
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        corners += ((mx + nx * bow, my + ny * bow),)
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


def _seg_box_interval(a, b, box: Box) -> tuple[float, float] | None:
    """Liang-Barsky: the segment's t-interval inside the closed box,
    clipped to [0, 1], or None if empty."""
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
    return (t_lo, t_hi)


seg_box_interval = _seg_box_interval  # public alias


def _seg_box_t(a, b, box: Box) -> float | None:
    """Entry t of the segment's interval inside the box, or None."""
    iv = _seg_box_interval(a, b, box)
    return None if iv is None else iv[0]


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


ANN_LABEL_LINE_H = 14.0


def ann_band_h(label: str) -> float:
    """The annotation label band's height: the 26px single-line band,
    grown only when the label carries manual lines (multi-line labels
    render one Text per line, so the band must fit them)."""
    n = len(label.split("\\n")) if label else 1
    return 26.0 if n <= 1 else 12.0 + n * ANN_LABEL_LINE_H


def annotation_label_rect(ann, member_boxes: list) -> tuple | None:
    """The label band of an AnnotationBox, in layout coordinates.

    (x, y, x2, y2) or None for an unlabelled box. The single source of
    the box/label geometry: the solver's strike measurement (an edge
    label riding through an annotation's label band is a reservation),
    the audit's ann-clash metric and the renderer's canvas expansion
    all consume this one formula. Inside-* labels live in the grown pad
    band; outside labels sit a band beyond the border.
    """
    if not member_boxes:
        return None
    if not getattr(ann, "label", ""):
        return None
    LABEL_H = ann_band_h(ann.label)
    pad = getattr(ann, "padding", 10)
    pt = ann.padding_top if ann.padding_top is not None else pad
    pr = ann.padding_right if ann.padding_right is not None else pad
    pb = ann.padding_bottom if ann.padding_bottom is not None else pad
    pl = ann.padding_left if ann.padding_left is not None else pad
    pos = getattr(ann, "label_position", "top")
    bx1 = min(b[0] for b in member_boxes) - pl
    by1 = min(b[1] for b in member_boxes) - pt
    bx2 = max(b[2] for b in member_boxes) + pr
    by2 = max(b[3] for b in member_boxes) + pb
    if pos == "inside-bottom":
        return (bx1, by2 - LABEL_H, bx2, by2)
    if pos == "inside-top":
        return (bx1, by1, bx2, by1 + LABEL_H)
    if pos == "top":
        return (bx1, by1 - LABEL_H, bx2, by1)
    if pos == "bottom":
        return (bx1, by2, bx2, by2 + LABEL_H)
    if pos == "left":
        return (bx1 - LABEL_H, by1, bx1, by2)
    return (bx2, by1, bx2 + LABEL_H, by2)  # right


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

def seg_enters_rect(a, b, box: Box) -> bool:
    """Does segment (a->b) pass through the box's interior?

    Touching the boundary at a single point (grazing a corner, leaving
    from a border point) does NOT count — the router's move legality
    depends on it: seeds sit ON the borders of their own rects.
    """
    iv = _seg_box_interval(a, b, box)
    return iv is not None and iv[0] < iv[1]


def point_seg_dist(p, a, b) -> float:
    """Distance from point p to segment (a, b)."""
    return _point_seg_dist(p, a, b)


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
    bow: float = 0.0,
) -> Strip:
    """Build the strip a routed edge sweeps.

    The label extent is measured by label_geometry on the longest leg
    (the placement the renderer draws); the corridor is the stroke
    half-width plus STRIP_PAD clearance; arrowheads sweep caps of
    ARROWHEAD_SIZE/2 beyond the corridor at each arrowed end. A bowed
    edge (bow != 0) sweeps the 3-point polyline through the curve's
    apex — the corridor covers the drawn arc's deviation.
    """
    pts = [(float(x), float(y)) for x, y in points]
    if bow and len(pts) == 2:
        nx, ny = _chord_normal(pts[0], pts[1])
        mx, my = (pts[0][0] + pts[1][0]) / 2.0, (pts[0][1] + pts[1][1]) / 2.0
        pts = [pts[0], (mx + nx * bow, my + ny * bow), pts[1]]
    half_w = stroke_width / 2 + STRIP_PAD
    cap = ARROWHEAD_SIZE / 2 + half_w
    label = None
    if label_text:
        lg = label_geometry(points, label_text, anchor_frac, bow)
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


# ---------------------------------------------------------------------------
# Clipped strips — shared-endpoint exemption
# ---------------------------------------------------------------------------

@dataclass
class ClipStrip:
    """A strip clipped against exemption boxes (the ancestor-or-self
    rects of the other edge's endpoints): near a shared endpoint node
    a later edge may hug — separation is only required beyond it.
    Carries the surviving corridor pieces, label extent and caps."""
    segs: list[tuple[tuple[float, float], tuple[float, float]]]
    half_w: float
    label: Box | None
    caps: list[tuple[tuple[float, float], float]]
    owner: str


def cut_seg(q0, q1, box: Box):
    """Cut the closed sub-interval of segment q0->q1 inside box out;
    return the remaining pieces (0, 1 or 2)."""
    iv = _seg_box_interval(q0, q1, box)
    if iv is None:
        return [(q0, q1)]
    t_lo, t_hi = iv
    if t_lo <= 0.0 and t_hi >= 1.0:
        return []
    dx, dy = q1[0] - q0[0], q1[1] - q0[1]

    def pt(t):
        return (q0[0] + dx * t, q0[1] + dy * t)

    out = []
    if t_lo > 1e-6:
        out.append((q0, pt(t_lo)))
    if t_hi < 1.0 - 1e-6:
        out.append((pt(t_hi), q1))
    return out


def clip_strip(strip: "Strip", exempt_infl: list[Box]) -> ClipStrip:
    """Clip a strip against inflated exemption boxes."""
    segs: list = []
    pts = strip.points
    for k in range(len(pts) - 1):
        pieces = [(pts[k], pts[k + 1])]
        for box in exempt_infl:
            nxt = []
            for q0, q1 in pieces:
                nxt.extend(cut_seg(q0, q1, box))
            pieces = nxt
        segs.extend(pieces)
    label = strip.label
    if label is not None and any(
        rects_overlap(label, box, eps=0.0) for box in exempt_infl
    ):
        label = None
    caps = []
    for pt, r in (
        [(pts[0], strip.arrow_start)] if strip.arrow_start else []
    ) + ([(pts[-1], strip.arrow_end)] if strip.arrow_end else []):
        if not any(b[0] < pt[0] < b[2] and b[1] < pt[1] < b[3]
                   for b in exempt_infl):
            caps.append((pt, r))
    return ClipStrip(segs=segs, half_w=strip.half_w, label=label,
                     caps=caps, owner=strip.owner)


def strip_hits_clip(strip: "Strip", clip: ClipStrip) -> bool:
    """Does a full strip collide with a clipped strip's surviving
    pieces (corridor, label, caps)?"""
    for i in range(len(strip.points) - 1):
        a, b = strip.points[i], strip.points[i + 1]
        for s0, s1 in clip.segs:
            if seg_seg_dist(a, b, s0, s1) < strip.half_w + clip.half_w:
                return True
        if clip.label is not None and seg_box_dist(a, b, clip.label) < strip.half_w:
            return True
        for cpt, cr in clip.caps:
            if point_seg_dist(cpt, a, b) < cr + strip.half_w:
                return True
    if strip.label is not None:
        for s0, s1 in clip.segs:
            if seg_box_dist(s0, s1, strip.label) < clip.half_w:
                return True
        if clip.label is not None and rects_overlap(strip.label, clip.label):
            return True
        for cpt, cr in clip.caps:
            if point_box_dist(cpt, strip.label) < cr:
                return True
    for cap_r, pt in ((strip.arrow_start, strip.points[0]),
                      (strip.arrow_end, strip.points[-1])):
        if cap_r <= 0:
            continue
        for s0, s1 in clip.segs:
            if point_seg_dist(pt, s0, s1) < cap_r + clip.half_w:
                return True
        if clip.label is not None and point_box_dist(pt, clip.label) < cap_r:
            return True
    return False

# Annotation label placement (2026-09-21 reviewer: the top band sat in
# the corridors edges ride and was neither clash-free nor preattentive;
# the inside-bottom band reads as the abstraction over everything above
# it). The DEFAULT position is the engine's choice; an author-declared
# position other than the default is the author's word.

ANN_POSITION_PREF = ("inside-bottom", "bottom", "top", "right", "left")


def ann_label_text_rect(ann, member_boxes, position=None):
    """The label TEXT's own rect for a position (not the full band).

    The band spans the members' union; the text is centred in it, so
    the honest strike target is the centred extent (the full-width band
    would strike edges nowhere near the glyphs).
    """
    if position is None:
        position = getattr(ann, "label_position", "top")
    if not getattr(ann, "label", ""):
        return None
    lr = annotation_label_rect(ann, member_boxes) if position == (
        getattr(ann, "label_position", "top") or "top") else None
    if lr is None:
        import dataclasses
        a2 = dataclasses.replace(ann, label_position=position) \
            if hasattr(ann, "label_position") else ann
        lr = annotation_label_rect(a2, member_boxes)
    if lr is None:
        return None
    text_w = len(ann.label) * 7.2 + 2 * 7.0
    if position in ("left", "right"):
        cy = (lr[1] + lr[3]) / 2
        return (lr[0], cy - text_w / 2, lr[2], cy + text_w / 2)
    cx = (lr[0] + lr[2]) / 2
    return (cx - text_w / 2, lr[1], cx + text_w / 2, lr[3])


def choose_annotation_position(ann, member_boxes, label_rects,
                               declared_default="top"):
    """Pick the annotation label's side: the first preference whose
    text rect clashes with no riding edge label; on total contention
    the preference order stands (the audit's ACLASH keeps measuring).

    label_rects: the riding edge labels as (x, y, x2, y2). A declared
    position other than the default is the author's word and wins.
    """
    declared = getattr(ann, "label_position", declared_default)
    if declared != declared_default:
        return declared
    if not getattr(ann, "label", ""):
        return declared
    best = declared
    for pos in ANN_POSITION_PREF:
        trect = ann_label_text_rect(ann, member_boxes, pos)
        if trect is None:
            continue
        if not any(rects_overlap(trect, lr) for lr in label_rects):
            return pos
    return best
