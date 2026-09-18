"""ggarch edge router — obstacle-aware shortest paths over strips (ADR-003).

Routes are found by search, not derived from endpoint geometry: A* over
a Hanan grid (endpoint and obstacle rect coordinates, duplicates
collapsed with a tolerance) with 8-neighbour moves, cost = length plus
a fixed turn penalty K. The search chooses exit and entry faces —
anchor candidates come from the grid (face centres, grid-line crossings
on the faces, and centre ± k*SEED_STEP offsets), so closest-opposing-
face pre-selection and the face-spreading post-pass retire into grid
seeding and emergent offsets. Declared/field-qualified anchors stay
pinned — author speech outranks heuristics.

The collision currency is the strip: path + stroke width + arrowhead +
the one-sided ADR-002 label extent (ggarch.geometry). Obstacles: node
rects (inflated by the corridor), the endpoint's own rects (interior
only), and earlier edges' strips — pairs and meshes route at distinct
offsets emergent from strip collisions, greedily after independent
edges. Annotation boxes/regions are meta elements — never obstacles
(they are not in the layout's node tree).

No box explosion: the arrangement is fixed input. When no collision-free
path exists the router returns the cheapest-collision path (obstacles
carry a soft penalty) and reports it — audited, never silent, never
hidden.
"""
from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from ggarch.layout import Rect, SolvedLayout, SolvedNode
from ggarch.model import Edge, GgarchFile, Model
from ggarch.instances import materialize_instances
from ggarch.geometry import (
    Box,
    Strip,
    STRIP_PAD,
    label_geometry,
    point_box_dist,
    point_seg_dist,
    rects_overlap,
    seg_box_dist,
    seg_box_interval,
    seg_enters_rect,
    seg_seg_dist,
    strip_for_edge,
)

# ---------------------------------------------------------------------------
# Tunables (measured via the audit: turns-per-edge and residual reports)
# ---------------------------------------------------------------------------

ROUTE_STROKE_W = 2.0   # px — planning assumption for the corridor width
TURN_PENALTY   = 30.0  # px per bend — fixed, not scaled by edge length;
                       # high enough that a path bends only to clear an
                       # obstacle (ADR-003 Resolved 1)
GRID_TOL       = 0.5  # px — duplicate grid coordinates collapsed within
SEED_STEP      = 6.0   # px between emergent face offsets (one corridor
                       # pair separation, so sibling edges find offsets)
SEED_INSET     = 4.0   # px — face seeds stay clear of face corners
BLOCK_PENALTY  = 500.0 # px — soft cost per obstacle entered when no
                       # clear path exists (cheapest-collision fallback)
MAX_POPS       = 6000  # A* expansion cap before the direct fallback
RELEVANT_MARGIN = 150.0  # px — obstacle-corridor relevance for the grid
LABEL_RETRIES  = 2     # label-strike nudges before residuals are reported


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Point:
    x: float
    y: float

    def __iter__(self):
        yield self.x
        yield self.y

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass
class RoutedEdge:
    """A routed edge ready for the renderer."""
    source_id: str
    target_id: str
    label: str
    edge_type: str     # edge type name (built-in or custom)
    style: str         # solid | dashed | dotted
    arrow: str         # forward | back | both | none
    url: str = ""      # if set, edge label is clickable
    # Waypoints: first = start anchor, last = end anchor.
    points: list[Point] = field(default_factory=list)
    # ADR-003 reporting: bend count, and the residual collisions of the
    # cheapest-collision path — (kind, target) pairs, kind in
    # {"node", "strip", "label"}; empty when the route is collision-free.
    turns: int = 0
    residuals: list[tuple[str, str]] = field(default_factory=list)
    # The swept strip this edge occupies — the shared collision currency
    # (the audit measures these; the renderer draws the path).
    strip: Strip | None = None

    @property
    def start(self) -> Point:
        return self.points[0]

    @property
    def end(self) -> Point:
        return self.points[-1]

    @property
    def mid(self) -> Point:
        """Midpoint of the path — used for label placement."""
        if len(self.points) == 2:
            return Point(
                (self.points[0].x + self.points[1].x) / 2,
                (self.points[0].y + self.points[1].y) / 2,
            )
        # For elbows, use the middle waypoint.
        return self.points[len(self.points) // 2]


@dataclass
class RoutedLayout:
    """Solved layout plus routed edges for one diagram view."""
    layout: SolvedLayout
    edges: list[RoutedEdge] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

_FACE_OFFSETS = {
    "top":    (0.5,  0.0),
    "bottom": (0.5,  1.0),
    "left":   (0.0,  0.5),
    "right":  (1.0,  0.5),
}


def _face_point(rect: Rect, face: str) -> Point:
    fx, fy = _FACE_OFFSETS[face]
    return Point(rect.x + rect.w * fx, rect.y + rect.h * fy)


def _rect_box(r: Rect) -> Box:
    return (r.x, r.y, r.x + r.w, r.y + r.h)


def _inflate(box: Box, d: float) -> Box:
    return (box[0] - d, box[1] - d, box[2] + d, box[3] + d)


def _dedupe(vals: Sequence[float]) -> list[float]:
    """Sorted unique coordinates, duplicates collapsed within GRID_TOL."""
    out: list[float] = []
    for v in sorted(vals):
        if not out or v - out[-1] > GRID_TOL:
            out.append(v)
    return out


# ---------------------------------------------------------------------------
# Grid seeding — the search chooses exit and entry faces
# ---------------------------------------------------------------------------

def _face_coords(pool: Sequence[float], lo: float, hi: float) -> list[float]:
    """Candidate coordinates along one face: grid-line crossings within
    the face (inset from the corners), the face centre, and centre ±
    k*SEED_STEP offsets (emergent spreading for edges sharing a face)."""
    lo2, hi2 = lo + SEED_INSET, hi - SEED_INSET
    if hi2 < lo2:
        lo2 = hi2 = (lo + hi) / 2
    # Centre first: the fast path prefers it on length ties, so the
    # unobstructed look stays the classic face-centre anchor.
    c = (lo + hi) / 2
    vals = [c]
    vals += [v for v in pool if lo2 <= v <= hi2]
    for k in range(1, 6):
        added = False
        for s in (c - k * SEED_STEP, c + k * SEED_STEP):
            if lo2 <= s <= hi2:
                vals.append(s)
                added = True
        if not added:
            break
    out: list[float] = []
    for v in vals:
        if not out or abs(v - out[-1]) > GRID_TOL:
            out.append(v)
    return out


def _face_seeds(rect: Rect, xs: Sequence[float], ys: Sequence[float]) -> list[Point]:
    """Anchor candidates on all four faces of a rect."""
    pts: list[Point] = []
    for v in _face_coords(xs, rect.x, rect.x + rect.w):
        pts.append(Point(v, rect.y))
        pts.append(Point(v, rect.y + rect.h))
    for v in _face_coords(ys, rect.y, rect.y + rect.h):
        pts.append(Point(rect.x, v))
        pts.append(Point(rect.x + rect.w, v))
    return pts


def _seed_ok(p: Point, obs_infl: Sequence[Box]) -> bool:
    """A seed is usable when it is not inside an inflated obstacle."""
    return not any(b[0] < p.x < b[2] and b[1] < p.y < b[3] for b in obs_infl)


# ---------------------------------------------------------------------------
# Strip clipping — shared-endpoint exemption
# ---------------------------------------------------------------------------

@dataclass
class _ClipStrip:
    """An earlier strip clipped against the current edge's exempt rects
    (ancestor-or-self of its endpoints): near a shared endpoint node a
    later edge may hug — separation is only required beyond it."""
    segs: list[tuple[tuple[float, float], tuple[float, float]]]
    half_w: float
    label: Box | None
    caps: list[tuple[tuple[float, float], float]]
    owner: str


def _cut_seg(q0, q1, box: Box):
    """Cut the closed sub-interval of segment q0->q1 inside box out;
    return the remaining pieces (0, 1 or 2)."""
    iv = seg_box_interval(q0, q1, box)
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


def _clip_strip(strip: Strip, exempt_infl: Sequence[Box]) -> _ClipStrip:
    segs: list = []
    pts = strip.points
    for k in range(len(pts) - 1):
        pieces = [(pts[k], pts[k + 1])]
        for box in exempt_infl:
            nxt = []
            for q0, q1 in pieces:
                nxt.extend(_cut_seg(q0, q1, box))
            pieces = nxt
        segs.extend(pieces)
    label = strip.label
    if label is not None and any(
        rects_overlap(label, box, eps=0.0) for box in exempt_infl
    ):
        label = None
    caps = [
        (pt, r) for pt, r in (
            [(pts[0], strip.arrow_start)] if strip.arrow_start else []
            + ([(pts[-1], strip.arrow_end)] if strip.arrow_end else [])
        )
        if not any(b[0] < pt[0] < b[2] and b[1] < pt[1] < b[3]
                   for b in exempt_infl)
    ]
    return _ClipStrip(segs=segs, half_w=strip.half_w, label=label,
                       caps=caps, owner=strip.owner)


# ---------------------------------------------------------------------------
# Search context
# ---------------------------------------------------------------------------

_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1),
         (1, 1), (1, -1), (-1, 1), (-1, -1)]
_ORTHO_DIRS = _DIRS[:4]


class _Ctx:
    """Per-edge search state: grid pools, obstacle boxes, clipped strips."""

    def __init__(self, starts, goals, obstacles, own_boxes, clips, clear,
                 dirs=None):
        self.obs = obstacles               # [(Box, id)] original boxes
        self.obs_infl = [_inflate(b, clear) for b, _ in obstacles]
        self.own = own_boxes                # endpoint rects (interior only)
        self.clips = clips
        self.clear = clear
        self.dirs = list(dirs) if dirs is not None else _DIRS
        xs: list[float] = [p.x for p in starts] + [p.x for p in goals]
        ys: list[float] = [p.y for p in starts] + [p.y for p in goals]
        d = clear + 1.0
        for box, _ in obstacles:
            xs += [box[0], box[2], box[0] - d, box[2] + d]
            ys += [box[1], box[3], box[1] - d, box[3] + d]
        for box in own_boxes:
            xs += [box[0], box[2]]
            ys += [box[1], box[3]]
        self.xs = _dedupe(xs)
        self.ys = _dedupe(ys)
        self._blocked: dict[int, bool] = {}
        self._seg_cache: dict[tuple, tuple[bool, float]] = {}

    # -- node legality ----------------------------------------------------
    def node_blocked(self, n: int) -> bool:
        """Inside an inflated obstacle (or an endpoint rect interior) —
        not a legal path node in hard mode."""
        v = self._blocked.get(n)
        if v is None:
            i, j = divmod(n, len(self.ys))
            x, y = self.xs[i], self.ys[j]
            v = any(b[0] < x < b[2] and b[1] < y < b[3]
                    for b in self.obs_infl) \
                or any(b[0] < x < b[2] and b[1] < y < b[3] for b in self.own)
            self._blocked[n] = v
        return v

    # -- segment legality ---------------------------------------------------
    # The grid graph is static during one search, so every segment's
    # legality and penalty is computed once and cached by its endpoints.
    def seg_eval(self, a, b) -> tuple[bool, float]:
        """(clear?, penalty) of the segment: clear when it misses every
        inflated obstacle, own rect interior, and earlier strip
        corridor; penalty counts the original-box crossings (soft
        cheapest-collision searches only)."""
        key = (a[0], a[1], b[0], b[1])
        hit = self._seg_cache.get(key)
        if hit is not None:
            return hit
        clear = True
        pen = 0.0
        for box in self.obs_infl:
            if seg_enters_rect(a, b, box):
                clear = False
                break
        if clear:
            for box in self.own:
                if seg_enters_rect(a, b, box):
                    clear = False
                    break
        strip_hit = False
        if clear:
            strip_hit = self._strip_hit(a, b)
            clear = not strip_hit
        if not clear:
            for box, _ in self.obs:
                if seg_enters_rect(a, b, box):
                    pen += BLOCK_PENALTY
            for box in self.own:
                if seg_enters_rect(a, b, box):
                    pen += BLOCK_PENALTY
            if strip_hit or self._strip_hit(a, b):
                pen += BLOCK_PENALTY
        out = (clear, pen)
        self._seg_cache[key] = out
        return out

    def seg_clear(self, a, b) -> bool:
        """Is the segment clear of every obstacle (inflated), own rect
        interior, and earlier strip corridor?"""
        return self.seg_eval(a, b)[0]

    def _strip_hit(self, a, b) -> bool:
        for c in self.clips:
            for s0, s1 in c.segs:
                if seg_seg_dist(a, b, s0, s1) < self.clear + c.half_w:
                    return True
            if c.label is not None and seg_box_dist(a, b, c.label) < self.clear:
                return True
            for cpt, cr in c.caps:
                if point_seg_dist(cpt, a, b) < cr + self.clear:
                    return True
        return False

    def seg_penalty(self, a, b) -> float:
        """Soft cost of a segment that may cross obstacles (original
        boxes — crossing the node is the defect)."""
        return self.seg_eval(a, b)[1]


# ---------------------------------------------------------------------------
# A* over the Hanan grid
# ---------------------------------------------------------------------------

def _astar(ctx: _Ctx, start_pts, goal_pts, soft: bool):
    """A* from any start seed to any goal seed. Returns the list of
    grid points or None (no path / cap exceeded)."""
    ny = len(ctx.ys)
    xi = {v: i for i, v in enumerate(ctx.xs)}
    yi = {v: j for j, v in enumerate(ctx.ys)}
    goal_nodes: set[int] = set()
    for p in goal_pts:
        if p.x in xi and p.y in yi:
            goal_nodes.add(xi[p.x] * ny + yi[p.y])
    if not goal_nodes:
        return None
    goals_xy = [(p.x, p.y) for p in goal_pts]

    def h_of(n):
        i, j = divmod(n, ny)
        x, y = ctx.xs[i], ctx.ys[j]
        return min(math.hypot(x - gx, y - gy) for gx, gy in goals_xy)

    dirs = ctx.dirs
    g: dict[tuple[int, int], float] = {}
    parent: dict[tuple[int, int], tuple[int, int] | None] = {}
    heap: list = []
    counter = 0
    for p in start_pts:
        if p.x not in xi or p.y not in yi:
            continue
        n = xi[p.x] * ny + yi[p.y]
        if not soft and ctx.node_blocked(n):
            continue
        key = (n, -1)
        g[key] = 0.0
        parent[key] = None
        heapq.heappush(heap, (h_of(n), counter, n, -1, 0.0))
        counter += 1

    closed: set[tuple[int, int]] = set()
    pops = 0
    while heap:
        _, _, n, d, gv = heapq.heappop(heap)
        key = (n, d)
        if key in closed or gv > g.get(key, math.inf):
            continue
        closed.add(key)
        pops += 1
        if pops > MAX_POPS:
            return None
        if n in goal_nodes:
            path = []
            k = key
            while k is not None:
                i, j = divmod(k[0], ny)
                path.append((ctx.xs[i], ctx.ys[j]))
                k = parent[k]
            path.reverse()
            return path
        i, j = divmod(n, ny)
        a = (ctx.xs[i], ctx.ys[j])
        for d_idx, (di, dj) in enumerate(dirs):
            i2, j2 = i + di, j + dj
            if not (0 <= i2 < len(ctx.xs) and 0 <= j2 < len(ctx.ys)):
                continue
            n2 = i2 * ny + j2
            b = (ctx.xs[i2], ctx.ys[j2])
            seg_len = math.hypot(b[0] - a[0], b[1] - a[1])
            if seg_len < 1e-9:
                continue
            if not soft:
                if ctx.node_blocked(n2) or not ctx.seg_clear(a, b):
                    continue
            turn = TURN_PENALTY if d >= 0 and d != d_idx else 0.0
            pen = ctx.seg_penalty(a, b) if soft else 0.0
            ngv = gv + seg_len + turn + pen
            nkey = (n2, d_idx)
            if ngv < g.get(nkey, math.inf):
                g[nkey] = ngv
                parent[nkey] = key
                heapq.heappush(
                    heap, (ngv + h_of(n2), counter, n2, d_idx, ngv))
                counter += 1
    return None


def _smooth(points, ctx: _Ctx):
    """Greedy shortcut smoothing: replace bendy sub-paths by direct
    segments whenever the direct segment is clear. Restores the
    diagonals the staircase-free grid search cannot express."""
    out = [points[0]]
    i = 0
    n = len(points)
    while i < n - 1:
        j = n - 1
        while j > i + 1 and not ctx.seg_clear(points[i], points[j]):
            j -= 1
        out.append(points[j])
        i = j
    return out


def _merge_collinear(points):
    """Drop waypoints that lie on the segment between their neighbours."""
    if len(points) <= 2:
        return points
    out = [points[0]]
    for k in range(1, len(points) - 1):
        ax, ay = out[-1]
        bx, by = points[k]
        cx, cy = points[k + 1]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cross) > 1e-6:
            out.append(points[k])
    out.append(points[-1])
    return out


def _count_turns(points) -> int:
    """Bends of the final polyline (the audit's turns-per-edge metric)."""
    if len(points) < 3:
        return 0
    turns = 0
    prev_dx = prev_dy = None
    for k in range(len(points) - 1):
        dx = points[k + 1][0] - points[k][0]
        dy = points[k + 1][1] - points[k][1]
        if prev_dx is not None and (
                abs(dx - prev_dx) > 1e-6 or abs(dy - prev_dy) > 1e-6):
            turns += 1
        prev_dx, prev_dy = dx, dy
    return turns


def _direct_pair(start_pts, goal_pts):
    """Closest (start, goal) seed pair ignoring obstacles — the
    cheapest-collision fallback when no clear path exists."""
    best = None
    for a in start_pts:
        for b in goal_pts:
            d = math.hypot(a.x - b.x, a.y - b.y)
            if best is None or d < best[0]:
                best = (d, a, b)
    if best is None:
        return None
    return [best[1], best[2]]


def _search_route(
    starts: list[Point],
    goals: list[Point],
    obstacles: Sequence[tuple[Box, str]],
    own_boxes: Sequence[Box],
    clips: Sequence[_ClipStrip],
    clear: float,
    soft: bool = False,
    orthogonal: bool = False,
):
    """Find a route from any start seed to any goal seed.

    Returns (points, hard) — points as a list of (x, y) tuples, hard
    True when collision-free. The fast path returns the best clear
    direct seed pair (length beats bends at any K); otherwise A*.
    """
    ctx = _Ctx(starts, goals, obstacles, own_boxes, clips, clear,
               dirs=_ORTHO_DIRS if orthogonal else None)
    return _search_route_inner(ctx, starts, goals, soft)


def _search_route_inner(ctx, starts, goals, soft):
    # Fast path: best clear direct seed pair (0 turns is unbeatable).
    best = None
    for a in starts:
        for b in goals:
            if not ctx.seg_clear((a.x, a.y), (b.x, b.y)):
                continue
            d = math.hypot(a.x - b.x, a.y - b.y)
            if d < 1e-9:
                continue
            if best is None or d < best[0]:
                best = (d, a, b)
    if best is not None:
        return [(best[1].x, best[1].y), (best[2].x, best[2].y)], True

    path = _astar(ctx, starts, goals, soft=False)
    if path is not None:
        pts = _merge_collinear(_smooth(path, ctx))
        return pts, True
    if soft:
        # Cheapest-collision: A* with obstacle penalties; direct pair if
        # even that fails. Crossings are reported, never hidden.
        path = _astar(ctx, starts, goals, soft=True)
        if path is not None:
            pts = _merge_collinear(_smooth(path, ctx))
            return pts, False
        direct = _direct_pair(starts, goals)
        return ([(p.x, p.y) for p in direct] if direct else None), False
    return None, False


# ---------------------------------------------------------------------------
# Route entry points
# ---------------------------------------------------------------------------

def _field_anchor(
    node: SolvedNode,
    field_id: str,
    face: str,
) -> Point:
    """Return the anchor point for a field-qualified edge endpoint.

    face: "right" | "left" | "top" | "bottom"
    The y (for left/right) or x (for top/bottom) is centred on the field row.
    """
    from ggarch.layout import FIELD_HEADER_H, FIELD_ROW_H
    field_index = next(
        (i for i, f in enumerate(node.fields) if f.id == field_id), 0
    )
    field_y = node.rect.y + FIELD_HEADER_H + field_index * FIELD_ROW_H + FIELD_ROW_H / 2
    if face == "right":
        return Point(node.rect.x2, field_y)
    elif face == "left":
        return Point(node.rect.x, field_y)
    elif face == "top":
        return Point(node.rect.cx, node.rect.y)
    else:  # bottom
        return Point(node.rect.cx, node.rect.y2)


def _pinned_field_anchors(edge, src_node, tgt_node):
    """Field-qualified endpoints stay pinned: the facing faces at the
    fields' mid-y (author speech outranks heuristics)."""
    src_rect, tgt_rect = src_node.rect, tgt_node.rect
    dx = abs(tgt_rect.cx - src_rect.cx)
    dy = abs(tgt_rect.cy - src_rect.cy)
    if dx >= dy:
        going_right = tgt_rect.cx >= src_rect.cx
        src_face = "right" if going_right else "left"
        tgt_face = "left" if going_right else "right"
    else:
        going_down = tgt_rect.cy >= src_rect.cy
        src_face = "bottom" if going_down else "top"
        tgt_face = "top" if going_down else "bottom"
    src_pt = (_field_anchor(src_node, edge.source_field, src_face)
              if edge.source_field else _face_point(src_rect, src_face))
    tgt_pt = (_field_anchor(tgt_node, edge.target_field, tgt_face)
              if edge.target_field else _face_point(tgt_rect, tgt_face))
    if dx >= dy and (edge.source_field or edge.target_field):
        mid_y = (src_pt.y + tgt_pt.y) / 2
        src_pt = Point(src_pt.x, mid_y)
        tgt_pt = Point(tgt_pt.x, mid_y)
    return src_pt, tgt_pt


def _route_edge(
    src_rect: Rect,
    tgt_rect: Rect,
    obstacles: Sequence[tuple[Box, str]] = (),
    strips: Sequence[Strip] = (),
    exempt_rects: Sequence[Rect] = (),
    src_anchor: Point | None = None,
    tgt_anchor: Point | None = None,
    extra_boxes: Sequence[Box] = (),
    soft: bool = True,
    orthogonal: bool = False,
) -> list[Point]:
    """Route between two rects with the obstacle-aware search.

    obstacles: non-exempt node rects (id-carrying, for residuals).
    strips: earlier routed strips (shared endpoints clipped via
    exempt_rects — ancestor-or-self of this edge's endpoints).
    src_anchor/tgt_anchor: pinned anchors (field-qualified endpoints).
    extra_boxes: label-nudge boxes (label-strike retries).
    Returns waypoints as Points.
    """
    clear = ROUTE_STROKE_W / 2 + STRIP_PAD
    own_boxes = [_rect_box(src_rect), _rect_box(tgt_rect)]
    # Nudge boxes (label-strike retries) block like obstacles but are
    # never reported as residuals — they are guidance, not geometry.
    obs = list(obstacles) + [(box, "") for box in extra_boxes]
    # Grid pruning: only obstacles within the endpoints' corridor
    # (bbox + RELEVANT_MARGIN) can matter — a route never wanders
    # beyond it, and the Hanan grid stays small.
    sb, tb = own_boxes[0], own_boxes[1]
    region = (min(sb[0], tb[0]) - RELEVANT_MARGIN,
              min(sb[1], tb[1]) - RELEVANT_MARGIN,
              max(sb[2], tb[2]) + RELEVANT_MARGIN,
              max(sb[3], tb[3]) + RELEVANT_MARGIN)
    obs = [(b, oid) for b, oid in obs
           if rects_overlap(b, region, eps=0.0)]
    pool_xs: list[float] = [src_rect.x, src_rect.x2, src_rect.cx,
                             tgt_rect.x, tgt_rect.x2, tgt_rect.cx]
    pool_ys: list[float] = [src_rect.y, src_rect.y2, src_rect.cy,
                             tgt_rect.y, tgt_rect.y2, tgt_rect.cy]
    d = clear + 1.0
    for b, _ in obs:
        pool_xs += [b[0], b[2], b[0] - d, b[2] + d]
        pool_ys += [b[1], b[3], b[1] - d, b[3] + d]
    xs0, ys0 = _dedupe(pool_xs), _dedupe(pool_ys)

    if src_anchor is not None:
        starts = [src_anchor]
    else:
        starts = _face_seeds(src_rect, xs0, ys0)
    if tgt_anchor is not None:
        goals = [tgt_anchor]
    else:
        goals = _face_seeds(tgt_rect, xs0, ys0)

    seeds_infl = [_inflate(b, clear) for b, _ in obs]
    starts = [p for p in starts if _seed_ok(p, seeds_infl)]
    goals = [p for p in goals if _seed_ok(p, seeds_infl)]
    if not starts or not goals:
        # Every seed on a face is blocked (a wall hugging the rect):
        # the cheapest-collision fallback still routes honestly.
        starts = starts or ([src_anchor] if src_anchor
                            else [_face_point(src_rect, _dominant_face(src_rect, tgt_rect))])
        goals = goals or ([tgt_anchor] if tgt_anchor
                          else [_face_point(tgt_rect, _dominant_face(tgt_rect, src_rect))])

    # Seed offset coordinates join the grid pools (offsets feed back
    # as crossings on faces).
    for p in starts + goals:
        pool_xs.append(p.x)
        pool_ys.append(p.y)
    xs, ys = _dedupe(pool_xs), _dedupe(pool_ys)
    starts = [p for p in starts if p.x in xs and p.y in ys]
    goals = [p for p in goals if p.x in xs and p.y in ys]

    exempt_infl = [_inflate(_rect_box(r), clear + 1.0)
                  for r in exempt_rects]
    clips = [_clip_strip(s, exempt_infl) for s in strips]

    pts, _hard = _search_route(
        starts, goals, obs, own_boxes, clips, clear,
        soft=soft, orthogonal=orthogonal)
    if pts is None:
        return []
    return [Point(x, y) for x, y in pts]


def _dominant_face(rect: Rect, other: Rect) -> str:
    """The face of `rect` pointing at `other` — last-resort seed."""
    dx = other.cx - rect.cx
    dy = other.cy - rect.cy
    if abs(dx) >= abs(dy):
        return "right" if dx >= 0 else "left"
    return "bottom" if dy >= 0 else "top"


def route_between(
    src_rect: Rect,
    tgt_rect: Rect,
    obstacles: Sequence[tuple[Box, str]] = (),
) -> list[Point]:
    """Public search entry: route between two rects around obstacles
    (cheapest-collision fallback allowed). Used by the solver's label
    contract and the state renderer."""
    return _route_edge(src_rect, tgt_rect, obstacles)


# ---------------------------------------------------------------------------
# Residuals and label retries
# ---------------------------------------------------------------------------

def _edge_strip(points, edge) -> Strip:
    pts = [(p.x, p.y) for p in points]
    return strip_for_edge(pts, ROUTE_STROKE_W, edge.arrow, edge.label,
                          0.5, owner=f"{edge.source}->{edge.target}")


def _path_residuals(points, obstacles, strips, clear) -> list[tuple[str, str]]:
    """Residual collisions of a cheapest-collision path (edge, obstacle,
    blocker) — audited, never hidden."""
    out: list[tuple[str, str]] = []
    pts = [(p.x, p.y) for p in points]
    for box, oid in obstacles:
        if any(seg_enters_rect(pts[i], pts[i + 1], box)
               for i in range(len(pts) - 1)):
            out.append(("node", oid))
    me = Strip(points=pts, half_w=clear)
    for s in strips:
        if me.hits_strip(s):
            out.append(("strip", s.owner))
    return out


def _label_offenders(points, edge, obstacles, strips):
    """(n_hits, nudge_boxes): regions this path's label strikes — node
    rects and earlier strips' corridors, labels and caps. Nudge boxes
    grow the struck region along the label's up direction so a retry
    path carries its label clear of it."""
    if not edge.label:
        return 0, []
    strip = _edge_strip(points, edge)
    if strip.label is None:
        return 0, []
    lg = label_geometry([(p.x, p.y) for p in points], edge.label, 0.5)
    nudges: list[Box] = []
    n = 0
    for box, oid in obstacles:
        if rects_overlap(strip.label, box):
            nudges.append(_grow_box_up(box, lg))
            n += 1
    for s in strips:
        hit = False
        for k in range(len(s.points) - 1):
            if seg_box_dist(s.points[k], s.points[k + 1],
                            strip.label) < s.half_w:
                hit = True
                break
        if not hit and s.label is not None and rects_overlap(strip.label, s.label):
            hit = True
        if not hit:
            for pt, r in _caps(s):
                if point_box_dist(pt, strip.label) < r:
                    hit = True
                    break
        if hit:
            nudge = (s.label if s.label is not None
                     else _bbox_of(s.points))
            nudges.append(_grow_box_up(nudge, lg))
            n += 1
    return n, nudges


def _caps(strip: Strip):
    """(point, cap radius) pairs of a strip's arrowed ends."""
    out = []
    if strip.arrow_start:
        out.append((strip.points[0], strip.arrow_start))
    if strip.arrow_end:
        out.append((strip.points[-1], strip.arrow_end))
    return out


def _bbox_of(points) -> Box:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _grow_box_up(box: Box, lg) -> Box:
    """Grow a box along the label's up direction by ~the label depth,
    so a path clearing the grown box carries its label clear of the
    struck region."""
    dx, dy = lg.up_x * 30.0, lg.up_y * 30.0
    return (min(box[0], box[0] + dx), min(box[1], box[1] + dy),
            max(box[2], box[2] + dx), max(box[3], box[3] + dy))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _collect_rects(layout: SolvedLayout) -> list[tuple[str, Rect]]:
    out: list[tuple[str, Rect]] = []

    def walk(n):
        out.append((n.id, n.rect))
        for c in n.children:
            walk(c)

    for n in layout.nodes:
        walk(n)
    return out


def _ancestors_map(layout: SolvedLayout) -> dict[str, set[str]]:
    """node id -> set of ancestor ids (excluding self)."""
    out: dict[str, set[str]] = {}

    def walk(n, chain):
        out[n.id] = set(chain)
        for c in n.children:
            walk(c, chain + [n.id])

    for n in layout.nodes:
        walk(n, [])
    return out


def _route_order(items):
    """Independent edges first, then endpoint-sharing groups (pairs,
    fans, meshes) greedily in declaration order — their offsets emerge
    from strip collisions (ADR-003 decision 8)."""
    parent: dict[str, str] = {}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for edge, _s, _t in items:
        union(edge.source, edge.target)
    groups: dict[str, list] = defaultdict(list)
    for it in items:
        groups[find(it[0].source)].append(it)
    out = []
    singles = [g for g in groups.values() if len(g) == 1]
    rest = [g for g in groups.values() if len(g) > 1]
    for g in singles + rest:
        out.extend(g)
    return out


def route(layout: SolvedLayout, model: Model, select) -> RoutedLayout:
    """Compute routed edges for all model edges whose endpoints are in layout."""
    clear = ROUTE_STROKE_W / 2 + STRIP_PAD

    # Materialized edges: instanced types are stamped out (subtrees +
    # per-instance edge expansion) so routing sees the same nodes the
    # solver laid out. Shared with the solver via ggarch.instances.
    _, edges = materialize_instances(select, model)

    all_rects = _collect_rects(layout)
    anc = _ancestors_map(layout)

    items = []
    for edge in edges:
        if select.edge_types and edge.type not in select.edge_types:
            continue
        if edge.source == edge.target:
            continue
        if layout.find(edge.source) is None or layout.find(edge.target) is None:
            continue
        items.append((edge, layout.find(edge.source), layout.find(edge.target)))
    ordered = _route_order(items)

    routed_edges: list[RoutedEdge] = []
    strips_done: list[Strip] = []

    for edge, src_node, tgt_node in ordered:
        src_rect, tgt_rect = src_node.rect, tgt_node.rect
        exempt_ids = (anc.get(edge.source, set()) | {edge.source}
                       | anc.get(edge.target, set()) | {edge.target})
        obstacles = [(_rect_box(r), nid)
                     for nid, r in all_rects if nid not in exempt_ids]
        exempt_rects = [r for nid, r in all_rects if nid in exempt_ids]

        # Field-qualified endpoints stay pinned.
        src_anchor = tgt_anchor = None
        if edge.source_field or edge.target_field:
            src_anchor, tgt_anchor = _pinned_field_anchors(
                edge, src_node, tgt_node)

        pts = _route_edge(
            src_rect, tgt_rect, obstacles, strips_done, exempt_rects,
            src_anchor, tgt_anchor)
        if not pts:
            # Complete search failure (degenerate geometry): fall back
            # to the dominant-face pair so the edge still renders.
            pts = [
                _face_point(src_rect, _dominant_face(src_rect, tgt_rect)),
                _face_point(tgt_rect, _dominant_face(tgt_rect, src_rect)),
            ]

        # Label retries: nudge the path clear of regions its label
        # strikes; residuals keep whatever remains (audited).
        n_hits, nudges = _label_offenders(pts, edge, obstacles, strips_done)
        for _ in range(LABEL_RETRIES):
            if n_hits == 0:
                break
            retry = _route_edge(
                src_rect, tgt_rect, obstacles, strips_done, exempt_rects,
                src_anchor, tgt_anchor, extra_boxes=nudges)
            if not retry:
                break
            r_hits, r_nudges = _label_offenders(
                retry, edge, obstacles, strips_done)
            if r_hits < n_hits:
                pts, n_hits, nudges = retry, r_hits, r_nudges
            else:
                break

        style = _default_style(edge.type)
        strip = _edge_strip(pts, edge)
        residuals = _path_residuals(pts, obstacles, strips_done, clear)
        routed_edges.append(RoutedEdge(
            source_id=edge.source,
            target_id=edge.target,
            label=edge.label,
            edge_type=edge.type,
            style=edge.style if edge.style else style,
            arrow=edge.arrow,
            url=edge.url,
            points=pts,
            turns=_count_turns([(p.x, p.y) for p in pts]),
            residuals=residuals,
            strip=strip,
        ))
        strips_done.append(strip)

    return RoutedLayout(layout=layout, edges=routed_edges)


def _default_style(edge_type: str) -> str:
    """Default line style for each semantic edge type."""
    return {
        "stream":  "dashed",
        "event":   "dashed",
        "data":    "solid",
        "api":     "solid",
        "control": "solid",
        "ipc":     "dotted",
    }.get(edge_type, "solid")
