"""ggarch edge router — the route vocabulary (ADR-003 as amended 0.26.1).

Routes come from a fixed vocabulary: **straight -> L (one bend) -> U
(two bends, deliberate)**. No route exceeds two bends — random
multi-bend polylines are out (user position, 2026-09-18). A route is
"the shortest arrow that will connect A to B without crossing nodes or
grazing": candidates are enumerated deterministically (face x ladder
anchors, cost = length + a fixed per-bend penalty), and the cheapest
clear route wins. Curved lines are rejected as a general vocabulary:
clearance on curves is not exactly measurable, and the corpus defects
never needed them (state-transition bows are a view-kind style, not
routing).

Hard obstacles: node rects inflated by the corridor (no crossing, no
graze), ancestor-or-self of either endpoint exempt — containers their
edges live in are passable. **Earlier edges' strips are NOT obstacles**
(the 0.26.0 measured root cause: hard strips in an open canvas let any
collision-free path win however absurd). Separation is deliberate:
anchor ladders with a reuse penalty spread shared faces and
anti-parallel pairs — offsets, not bends — and any residual overlap is
audited, never routed around. Annotation boxes/regions are meta
elements — never obstacles (they are not in the layout's node tree).

Field-qualified anchors stay pinned — author speech outranks
heuristics. No box explosion: the arrangement is fixed input. When no
clear route exists the router returns the fewest-crossing candidate
and reports it — audited, never silent, never hidden.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace as _dc_replace
from typing import Sequence

from ggarch.layout import Rect, SolvedLayout, SolvedNode
from ggarch.model import Edge, GgarchFile, Model
from ggarch.instances import materialize_instances
from ggarch.geometry import (
    Box,
    ClipStrip,
    clip_strip,
    strip_hits_clip,
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
# Tunables (measured via the audit: turns-per-edge, ratio, residuals)
# ---------------------------------------------------------------------------

ROUTE_STROKE_W = 2.0   # px — planning assumption for the corridor width
TURN_PENALTY   = 40.0  # px per bend — the exchange rate: a bend must
                       # save more length than it costs (ADR-003
                       # Resolved 1, kept by the 0.26.1 amendment)
SEED_STEP      = 6.0   # px between ladder offsets (one corridor pair
                       # separation, so shared faces find offsets)
SEED_INSET     = 6.0   # px — anchors stay clear of face corners (the
                       # near-corner 45° entry fix)
LADDER_K       = 3     # ladder half-depth: centre ± k*step — deep enough
                       # that an L dodges an obstacle beside the face
U_MARGINS      = (14.0, 30.0, 60.0)  # U run distance beyond both rects
ANCHOR_REUSE_COST = 8.0  # px — prefer unused face anchors (deliberate
                         # offsets for shared faces / anti-parallel pairs).
                         # Must exceed the SEED_STEP ladder (6px) so a
                         # used slot never beats a fresh offset.
RELEVANT_MARGIN = 150.0  # px — obstacle-corridor relevance pruning
LABEL_NODE_COST = 80.0   # px — the price of a route whose label strikes
                         # a node: two bends' worth, so a cheap detour or
                         # a neighbouring ladder slot beats the strike,
                         # but a forced strike beats a monster detour
LABEL_OTHER_COST = 24.0  # px — label overlapping an earlier strip's
                         # corridor or label: must exceed the ladder step
                         # (6px) twice over, so a farther anchor slot is
                         # cheaper than clashing labels (lesser, audited
                         # defect)
HINT_MISS_COST = 18.0    # px — ignoring a fan-slot / pair-bias anchor
                         # hint: hints encode predictable, distributed
                         # anchor points and parallel pair strokes; a
                         # clear hinted route beats an unhinted one
                         # unless the hinted geometry is blocked
PAIR_BIAS     = 6.0      # px — the first edge of an anti-parallel pair
                         # biases this far off the face centre; its
                         # reverse mirrors to −bias: two parallel
                         # strokes 12px apart, symmetric about the axis
CENTRE_MISS_COST = 18.0  # px — a deliberate form (L/U) anchoring off
                         # the face centre: arrows start/end in the
                         # middle of an edge; offsets are for fans and
                         # for dodging blocked centres only


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
    # Traceability (0.26.1): direct = border-to-border distance between
    # the endpoint rects (the shortest arrow that could connect them);
    # ratio = path length / direct. The metrics that make monster
    # detours measurable (0.26.0 measured 8.8x with these hidden).
    direct: float = 0.0
    ratio: float = 1.0
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


def _snap(v: float) -> float:
    """Quantize a coordinate: the solver's floating-point noise
    (run-to-run 1e-13 jitter) must not flip tie-breaking in the search
    — routes are deterministic by construction."""
    return round(v, 6)


def _snap_box(box: Box) -> Box:
    return (_snap(box[0]), _snap(box[1]), _snap(box[2]), _snap(box[3]))


def _snap_rect(r: Rect) -> Box:
    return _snap_box((r.x, r.y, r.x + r.w, r.y + r.h))


# ---------------------------------------------------------------------------
# The route vocabulary: straight -> L -> U
# ---------------------------------------------------------------------------

_FACE_ORDER = ("right", "left", "bottom", "top")


def _border_distance(sr: Rect, tr: Rect) -> float:
    """Border-to-border distance between two rects — the shortest
    arrow that could connect them (the traceability yardstick)."""
    dx = max(tr.x - (sr.x + sr.w), sr.x - (tr.x + tr.w), 0.0)
    dy = max(tr.y - (sr.y + sr.h), sr.y - (tr.y + tr.h), 0.0)
    return math.hypot(dx, dy)


def _anchor_ladder(rect: Rect) -> dict[str, list[Point]]:
    """Anchor candidates per face: the face centre and centre ±
    k*SEED_STEP along the face, clamped inside the face with a
    SEED_INSET corner margin (the near-corner 45° entry fix), snapped.
    Deterministic order: centre first, then alternating offsets."""
    out: dict[str, list[Point]] = {}
    for face in _FACE_ORDER:
        on_width = face in ("top", "bottom")
        lo, hi = ((rect.x, rect.x + rect.w) if on_width
                  else (rect.y, rect.y + rect.h))
        c = (lo + hi) / 2.0
        vals: list[float] = []
        if hi - lo < 2 * SEED_INSET:
            vals = [_snap(c)]
        else:
            # Fractional step: proportional to the face's usable span
            # (min SEED_STEP), so slots sit at predictable marks —
            # 1/6th of the span apart — on faces of any width, and a
            # k=3 ladder reaches past obstacles hugging the face.
            step = max(SEED_STEP, (hi - lo - 2 * SEED_INSET) / 6.0)
            for k in range(0, LADDER_K + 1):
                raw = ((c,) if k == 0
                       else (c - k * step, c + k * step))
                for v in raw:
                    v = min(max(_snap(v), lo + SEED_INSET),
                            hi - SEED_INSET)
                    if all(abs(v - u) > 1e-9 for u in vals):
                        vals.append(v)
        pts: list[Point] = []
        for v in vals:
            if face == "right":
                pts.append(Point(_snap(rect.x + rect.w), v))
            elif face == "left":
                pts.append(Point(_snap(rect.x), v))
            elif face == "top":
                pts.append(Point(v, _snap(rect.y)))
            else:
                pts.append(Point(v, _snap(rect.y + rect.h)))
        out[face] = pts
    return out


def _candidate_routes(
    src_rect: Rect, tgt_rect: Rect,
    src_ladder: dict[str, list[Point]],
    tgt_ladder: dict[str, list[Point]],
):
    """Deterministic candidate routes: for every anchor pair, the
    straight line; for perpendicular faces, both L orientations (one
    bend); for same-facing faces, the four U families at each U margin
    (two bends — the deliberate shape for topology that demands it).
    Yields (points, bends, form_rank, u_mi, src_face, tgt_face,
    src_i, tgt_i)."""
    for fs_i, fs in enumerate(_FACE_ORDER):
        for si, a in enumerate(src_ladder[fs]):
            for ft_i, ft in enumerate(_FACE_ORDER):
                for ti, b in enumerate(tgt_ladder[ft]):
                    # Straight — always a candidate, any angle.
                    yield ([a, b], 0, 0, -1, fs, ft, si, ti)
                    perp = ((fs in ("right", "left"))
                            != (ft in ("right", "left")))
                    if perp:
                        # L, both orientations (one bend). The bend is
                        # determined by the anchor pair; legs that
                        # re-enter an endpoint's interior are rejected
                        # by the own-interior check.
                        yield ([a, Point(b.x, a.y), b], 1, 1, -1,
                               fs, ft, si, ti)
                        yield ([a, Point(a.x, b.y), b], 1, 2, -1,
                               fs, ft, si, ti)
                    elif fs == ft:
                        # U families: out along the face normal, run
                        # parallel beyond both rects, back in.
                        for mi, m in enumerate(U_MARGINS):
                            if fs == "right":
                                run = max(src_rect.x + src_rect.w,
                                          tgt_rect.x + tgt_rect.w) + m
                                pts = [a, Point(run, a.y),
                                       Point(run, b.y), b]
                            elif fs == "left":
                                run = min(src_rect.x, tgt_rect.x) - m
                                pts = [a, Point(run, a.y),
                                       Point(run, b.y), b]
                            elif fs == "bottom":
                                run = max(src_rect.y + src_rect.h,
                                          tgt_rect.y + tgt_rect.h) + m
                                pts = [a, Point(a.x, run),
                                       Point(b.x, run), b]
                            else:  # top
                                run = min(src_rect.y, tgt_rect.y) - m
                                pts = [a, Point(a.x, run),
                                       Point(b.x, run), b]
                            yield (pts, 2, 3, mi, fs, ft, si, ti)


class _Search:
    """Per-edge evaluation state: pruned obstacles, own interiors, leg
    cache, earlier strips (for label-strike scoring), and the label."""

    def __init__(self, src_rect, tgt_rect, obstacles, own_boxes,
                 extra_boxes, clear, label="", clips=()):
        sb = _snap_rect(src_rect)
        tb = _snap_rect(tgt_rect)
        region = (min(sb[0], tb[0]) - RELEVANT_MARGIN,
                  min(sb[1], tb[1]) - RELEVANT_MARGIN,
                  max(sb[2], tb[2]) + RELEVANT_MARGIN,
                  max(sb[3], tb[3]) + RELEVANT_MARGIN)
        self.obs = [(b, oid) for b, oid in obstacles
                    if rects_overlap(b, region, eps=0.0)]
        self.obs += [(_snap_box(b), "") for b in extra_boxes]
        self.obs_infl = [_inflate(b, clear) for b, _ in self.obs]
        self.clear = clear
        # The audit's interior inset (0.5px): an anchor with float noise
        # ~1e-13 inside its own box must still be able to leave.
        self.own_inset = [
            (box[0] + 0.5, box[1] + 0.5, box[2] - 0.5, box[3] - 0.5)
            for box in own_boxes]
        self.label = label
        self.clips = clips
        self._legs: dict[tuple, tuple[bool, tuple[str, ...]]] = {}

    def leg(self, ax, ay, bx, by):
        """(clear, crossing ids) of one leg: clear when it keeps the
        corridor distance from every obstacle (exact segment-box
        distance — Liang-Barsky on an inflated box misses exact corner
        tangency) and neither endpoint's interior is entered; crossings
        count ORIGINAL-box interior entries (the soft fallback's
        currency)."""
        key = (_snap(ax), _snap(ay), _snap(bx), _snap(by))
        hit = self._legs.get(key)
        if hit is None:
            a = (key[0], key[1])
            b = (key[2], key[3])
            clear = True
            crossings: list[str] = []
            for box, oid in self.obs:
                if seg_box_dist(a, b, box) < self.clear:
                    clear = False
                    # Any corridor violation counts against the soft
                    # candidate: grazes are defects too, so the
                    # fewest-crossing fallback minimizes them.
                    if oid:
                        crossings.append(oid)
            if clear:
                for box in self.own_inset:
                    if seg_enters_rect(a, b, box):
                        clear = False
                        break
            hit = (clear, tuple(crossings))
            self._legs[key] = hit
        return hit

    def stroke_label_hits(self, pts):
        """How many earlier edges' LABEL boxes this route's STROKE
        passes under — the drawn stroke would overprint their text."""
        if not self.clips:
            return 0
        hits = 0
        for c in self.clips:
            if c.label is None:
                continue
            for i in range(len(pts) - 1):
                if seg_box_dist((pts[i].x, pts[i].y),
                                (pts[i + 1].x, pts[i + 1].y),
                                c.label) < c.half_w:
                    hits += 1
                    break
        return hits

    def label_score(self, pts):
        """(node_hits, other_hits) of the label this route would draw:
        the label strip vs node rects (weight-heavy — nodes are solid)
        and vs earlier strips' corridors, labels and caps."""
        if not self.label:
            return 0, 0
        lg = label_geometry([(p.x, p.y) for p in pts], self.label, 0.5)
        if lg.strip is None:
            return 0, 0
        node_hits = 0
        for box, oid in self.obs:
            if oid and rects_overlap(lg.strip, box):
                node_hits += 1
        other = 0
        for c in self.clips:
            hit = False
            for s0, s1 in c.segs:
                if seg_box_dist(s0, s1, lg.strip) < c.half_w:
                    hit = True
                    break
            if not hit and c.label is not None \
                    and rects_overlap(lg.strip, c.label):
                hit = True
            if not hit:
                for cpt, cr in c.caps:
                    if point_box_dist(cpt, lg.strip) < cr:
                        hit = True
                        break
            if hit:
                other += 1
        return node_hits, other


def _face_coord(p: Point, face: str) -> float:
    """The coordinate along the face (y for left/right, x otherwise)."""
    return p.y if face in ("right", "left") else p.x


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


def _forms(src_rect, tgt_rect, a: Point, b: Point, fs: str, ft: str,
           bias: float | None = None, orthogonal: bool = False):
    """The vocabulary forms for one anchor pair, in preference order:
    straight; both L orientations when the faces are perpendicular;
    the U family when the faces are the same (one per U margin).
    bias: the anti-parallel pair's symmetric off-centre bias — the U
    run shifts by it so the pair's strokes run parallel. orthogonal:
    declared-orthogonal views reject diagonal legs."""
    # Declared-orthogonal views reject the DIAGONAL straight; the L and
    # U legs are axis-aligned by construction.
    dx, dy = abs(b.x - a.x), abs(b.y - a.y)
    if not (orthogonal and dx > 1e-6 and dy > 1e-6):
        yield ([a, b], 0, 0, -1)
    perp = ((fs in ("right", "left")) != (ft in ("right", "left")))
    if perp:
        yield ([a, Point(b.x, a.y), b], 1, 1, -1)
        yield ([a, Point(a.x, b.y), b], 1, 2, -1)
        if orthogonal:
            # Corridor-shifted L (2026-09-19, edge-aware floor): when
            # rows are aligned across columns (the weak align-middle),
            # a row-diagonal edge's plain L runs along a face line and
            # clips the intervening node's corner. Shifting the long
            # leg into the inter-row corridor (14) — or past a same-row
            # blocker (30, 60) — keeps it clear at the cost of the
            # second bend, inside the vocabulary's two-bend budget.
            for m in U_MARGINS:
                if fs in ("top", "bottom"):
                    sgn = 1 if fs == "bottom" else -1
                    y = a.y + sgn * m
                    yield ([a, Point(a.x, y), Point(b.x, y), b], 2, 4, -1)
                else:
                    sgn = 1 if fs == "right" else -1
                    x = a.x + sgn * m
                    yield ([a, Point(x, a.y), Point(x, b.y), b], 2, 4, -1)
    elif fs == ft:
        shift = bias if bias is not None else 0.0
        for mi, m in enumerate(U_MARGINS):
            if fs == "right":
                run = max(src_rect.x + src_rect.w,
                          tgt_rect.x + tgt_rect.w) + m + shift
                yield ([a, Point(run, a.y), Point(run, b.y), b], 2, 3, mi)
            elif fs == "left":
                run = min(src_rect.x, tgt_rect.x) - m + shift
                yield ([a, Point(run, a.y), Point(run, b.y), b], 2, 3, mi)
            elif fs == "bottom":
                run = max(src_rect.y + src_rect.h,
                          tgt_rect.y + tgt_rect.h) + m + shift
                yield ([a, Point(a.x, run), Point(b.x, run), b], 2, 3, mi)
            else:  # top
                run = min(src_rect.y, tgt_rect.y) - m + shift
                yield ([a, Point(a.x, run), Point(b.x, run), b], 2, 3, mi)





def _route_candidates_eval(
    src_rect: Rect, tgt_rect: Rect,
    src_ladder: dict[str, list[Point]],
    tgt_ladder: dict[str, list[Point]],
    search: _Search,
    src_key: str = "", tgt_key: str = "",
    used_anchors: dict | None = None,
    pinned: bool = False,
    hints: dict | None = None,
    pair_bias: float | None = None,
    orthogonal: bool = False,
):
    """Evaluate every vocabulary candidate. Returns (best_clear,
    best_soft): each is (points, bends, cost, order, crossings) or
    None. cost = length + TURN_PENALTY*bends + anchor reuse + label
    costs + hint misses; `order` makes selection fully deterministic.
    Soft = fewest node crossings, then cheapest — reported, never
    hidden. hints: predictable anchor coordinates per (side, face)
    (fan slots, mirrored pair strokes); pair_bias: symmetric
    off-centre bias for the first edge of an anti-parallel pair;
    orthogonal: reject diagonal legs (declared orthogonal views)."""
    best_clear = None   # (points, bends, cost, order, ())
    best_soft = None    # (points, bends, cost, order, crossings)
    hints = hints or {}

    def _center(rect: Rect, face: str) -> float:
        lo, hi = ((rect.x, rect.x + rect.w) if face in ("top", "bottom")
                  else (rect.y, rect.y + rect.h))
        return (lo + hi) / 2.0

    for fs_i, fs in enumerate(_FACE_ORDER):
        for si, a in enumerate(src_ladder[fs]):
            for ft_i, ft in enumerate(_FACE_ORDER):
                for ti, b in enumerate(tgt_ladder[ft]):
                    direct = math.hypot(b.x - a.x, b.y - a.y)
                    if best_clear is not None and \
                            direct >= best_clear[2]:
                        continue
                    for (pts, bends, form_rank, u_mi) in _forms(
                            src_rect, tgt_rect, a, b, fs, ft,
                            bias=pair_bias, orthogonal=orthogonal):
                        if best_clear is not None and \
                                direct + TURN_PENALTY * bends >= \
                                best_clear[2]:
                            continue
                        reuse = 0.0
                        if used_anchors is not None and not pinned:
                            # Keyed by (node, face) regardless of edge
                            # role: an anti-parallel pair's reverse
                            # edge must see the forward edge's slots.
                            if _face_coord(a, fs) in used_anchors.get(
                                    (src_key, fs), ()):
                                reuse += ANCHOR_REUSE_COST
                            if _face_coord(b, ft) in used_anchors.get(
                                    (tgt_key, ft), ()):
                                reuse += ANCHOR_REUSE_COST
                        cost = direct + TURN_PENALTY * bends + reuse
                        # Deliberate forms anchor at face centres
                        # (review round 2): a U or L reads best
                        # leaving/entering the middle of an edge —
                        # ladder offsets are for fan distribution
                        # (straights) and for dodging blocked centres,
                        # never for corner-hugging deliberate shapes.
                        if bends > 0:
                            if abs(_face_coord(a, fs)
                                   - _center(src_rect, fs)) > 0.5:
                                cost += CENTRE_MISS_COST
                            if abs(_face_coord(b, ft)
                                   - _center(tgt_rect, ft)) > 0.5:
                                cost += CENTRE_MISS_COST
                        # Hint misses: a candidate away from its
                        # predictable slot (fan distribution, pair
                        # parallelism) pays, so hinted routes win.
                        sh = hints.get("src", {}).get(fs)
                        if sh is not None and \
                                abs(_face_coord(a, fs) - sh) > 0.5:
                            cost += HINT_MISS_COST
                        th = hints.get("tgt", {}).get(ft)
                        if th is not None and \
                                abs(_face_coord(b, ft) - th) > 0.5:
                            cost += HINT_MISS_COST
                        if pair_bias is not None:
                            ba = abs(_face_coord(a, fs)
                                     - (_center(src_rect, fs) + pair_bias))
                            bb = abs(_face_coord(b, ft)
                                     - (_center(tgt_rect, ft) + pair_bias))
                            if ba > 0.5 or bb > 0.5:
                                cost += HINT_MISS_COST
                        if best_clear is not None and \
                                cost >= best_clear[2]:
                            continue
                        clear = True
                        crossings: list[str] = []
                        for i in range(len(pts) - 1):
                            ok, hits = search.leg(
                                pts[i].x, pts[i].y,
                                pts[i + 1].x, pts[i + 1].y)
                            if not ok:
                                clear = False
                            for h in hits:
                                if h not in crossings:
                                    crossings.append(h)
                        node_hits = other_hits = 0
                        if search.label:
                            node_hits, other_hits = search.label_score(pts)
                        other_hits += search.stroke_label_hits(pts)
                        cost += (LABEL_NODE_COST * node_hits
                                 + LABEL_OTHER_COST * other_hits)
                        order = (fs_i, ft_i, si, ti, form_rank,
                                 u_mi if u_mi >= 0 else 0)
                        if clear:
                            if best_clear is None or \
                                    (cost, order) < (best_clear[2],
                                                     best_clear[3]):
                                best_clear = (pts, bends, cost, order, ())
                        elif best_soft is None or \
                                (len(crossings), cost, order) < (
                                    len(best_soft[4]), best_soft[2],
                                    best_soft[3]):
                            best_soft = (pts, bends, cost, order,
                                         tuple(crossings))
    return best_clear, best_soft


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
    else:
        # Horizontal faces: field rows are full-width, so there is no
        # per-field x — spread anchors across the face by field index.
        # Invariant: same field -> same anchor (two FKs referencing one
        # column converge on it, an honest fan); distinct fields ->
        # distinct anchors (two FK columns are two origins, never one
        # overdrawn stroke). n=1 lands on the face centre.
        n = max(len(node.fields), 1)
        x = node.rect.x + node.rect.w * (field_index + 1) / (n + 1)
        return Point(x, node.rect.y if face == "top" else node.rect.y2)


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


def _route_edge_full(
    src_rect: Rect,
    tgt_rect: Rect,
    obstacles: Sequence[tuple[Box, str]] = (),
    strips: Sequence[Strip] = (),
    exempt_rects: Sequence[Rect] = (),
    src_anchor: Point | None = None,
    tgt_anchor: Point | None = None,
    extra_boxes: Sequence[Box] = (),
    soft: bool = True,
    src_key: str = "",
    tgt_key: str = "",
    used_anchors: dict | None = None,
    label: str = "",
    hints: dict | None = None,
    pair_bias: float | None = None,
    orthogonal: bool = False,
) -> tuple[list[Point], bool]:
    """Route between two rects within the vocabulary.

    Returns (points, clear). obstacles: non-exempt node rects
    (id-carrying, for residuals); strips: earlier routed strips —
    NOT obstacles under the 0.26.1 amendment, but their clipped
    corridors score label strikes; exempt_rects: ancestor-or-self
    rects (passable interiors); src_anchor/tgt_anchor: pinned anchors
    (field-qualified endpoints); extra_boxes: hard unreported boxes;
    src_key/tgt_key + used_anchors: deliberate offset bookkeeping for
    shared faces / anti-parallel pairs; label: the edge label, whose
    strike cost participates in the candidate cost.
    """
    clear = ROUTE_STROKE_W / 2 + STRIP_PAD
    obs = [(_snap_box(b), oid) for b, oid in obstacles]
    exempt_infl = [_inflate(_snap_rect(r), clear + 4.0)
                   for r in exempt_rects]
    clips = [clip_strip(s, exempt_infl) for s in strips]
    search = _Search(src_rect, tgt_rect, obs,
                     [_snap_rect(src_rect), _snap_rect(tgt_rect)],
                     extra_boxes, clear, label=label, clips=clips)

    if src_anchor is not None or tgt_anchor is not None:
        # Pinned anchors (field-qualified endpoints stay pinned): one
        # anchor per side, straight and both L orientations.
        a = Point(_snap(src_anchor.x), _snap(src_anchor.y)) \
            if src_anchor is not None else None
        b = Point(_snap(tgt_anchor.x), _snap(tgt_anchor.y)) \
            if tgt_anchor is not None else None
        src_ladder = {f: ([a] if a is not None else _anchor_ladder(src_rect)[f])
                      for f in _FACE_ORDER}
        tgt_ladder = {f: ([b] if b is not None else _anchor_ladder(tgt_rect)[f])
                      for f in _FACE_ORDER}
        if a is not None and b is not None:
            best_clear, best_soft = _pinned_candidates(
                src_rect, tgt_rect, a, b, search, orthogonal=orthogonal)
        else:
            best_clear, best_soft = _route_candidates_eval(
                src_rect, tgt_rect, src_ladder, tgt_ladder, search,
                src_key, tgt_key, used_anchors,
                pinned=a is not None or b is not None,
                hints=hints, pair_bias=pair_bias, orthogonal=orthogonal)
    else:
        src_ladder = _anchor_ladder(src_rect)
        tgt_ladder = _anchor_ladder(tgt_rect)
        best_clear, best_soft = _route_candidates_eval(
            src_rect, tgt_rect, src_ladder, tgt_ladder, search,
            src_key, tgt_key, used_anchors,
            hints=hints, pair_bias=pair_bias, orthogonal=orthogonal)

    chosen = best_clear if best_clear is not None else \
        (best_soft if soft else None)
    if chosen is None:
        # Degenerate geometry (no candidate at all): dominant-face
        # pair so the edge still renders.
        return [_face_point(src_rect, _dominant_face(src_rect, tgt_rect)),
                _face_point(tgt_rect, _dominant_face(tgt_rect, src_rect))], \
            False
    pts, bends = chosen[0], chosen[1]
    return [Point(p.x, p.y) for p in pts], best_clear is not None


def _nearest_face(rect: Rect, p: Point) -> str:
    """Which face a point lies on (the anchor bookkeeping's key)."""
    dl = abs(p.x - rect.x)
    dr = abs(p.x - (rect.x + rect.w))
    dt = abs(p.y - rect.y)
    db = abs(p.y - (rect.y + rect.h))
    return min(("left", dl), ("right", dr), ("top", dt),
               ("bottom", db), key=lambda kv: kv[1])[0]


def _pinned_candidates(src_rect, tgt_rect, a: Point, b: Point, search,
                       orthogonal: bool = False):
    """Vocabulary candidates for a pinned anchor pair: the straight
    line and both L orientations (the bend is free; the anchors are
    not). U forms need same-facing faces, which a pinned pair does not
    declare — layout or the un-pinned ladder owns those."""
    best_clear = None
    best_soft = None
    direct = math.hypot(b.x - a.x, b.y - a.y)
    forms = []
    if not orthogonal or abs(b.x - a.x) < 1e-6 or abs(b.y - a.y) < 1e-6:
        forms.append(([a, b], 0))
    forms.append(([a, Point(b.x, a.y), b], 1))
    forms.append(([a, Point(a.x, b.y), b], 1))
    for pts, bends in forms:
        clear = True
        crossings: list[str] = []
        for i in range(len(pts) - 1):
            ok, hits = search.leg(pts[i].x, pts[i].y,
                                  pts[i + 1].x, pts[i + 1].y)
            if not ok:
                clear = False
            for h in hits:
                if h not in crossings:
                    crossings.append(h)
        cost = direct + TURN_PENALTY * bends
        if search.label:
            node_hits, other_hits = search.label_score(pts)
            cost += LABEL_NODE_COST * node_hits \
                + LABEL_OTHER_COST * other_hits
        order = (bends, len(pts))
        if clear:
            if best_clear is None or (cost, order) < best_clear[2:4]:
                best_clear = (pts, bends, cost, order, ())
        elif best_soft is None or (len(crossings), cost, order) < \
                (len(best_soft[4]), best_soft[2], best_soft[3]):
            best_soft = (pts, bends, cost, order, tuple(crossings))
    return best_clear, best_soft


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
    used_anchors: dict | None = None,
    src_key: str = "",
    tgt_key: str = "",
    hints: dict | None = None,
    pair_bias: float | None = None,
    orthogonal: bool = False,
) -> list[Point]:
    """Route between two rects within the vocabulary (straight -> L ->
    U; no route exceeds two bends). `orthogonal` retires the retired
    flag as a DECLARED view option: when True, diagonal legs are
    rejected (the snap-to-grid vocabulary). hints/pair_bias: the
    predictable-anchor and parallel-pair bookkeeping."""
    pts, _clear = _route_edge_full(
        src_rect, tgt_rect, obstacles, strips, exempt_rects,
        src_anchor, tgt_anchor, extra_boxes, soft,
        src_key=src_key, tgt_key=tgt_key, used_anchors=used_anchors,
        hints=hints, pair_bias=pair_bias, orthogonal=orthogonal)
    return pts


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


def _path_residuals(points, obstacles, strips, clear,
                    exempt_rects=()) -> list[tuple[str, str]]:
    """Residual collisions of a cheapest-collision path (edge, obstacle,
    blocker) — audited, never hidden. Node residuals are distance-based:
    a graze (within the corridor of a node) is a defect exactly like a
    crossing. Strip residuals are measured against clipped strips: near
    a shared endpoint the hug is by design, not a collision."""
    out: list[tuple[str, str]] = []
    pts = [(p.x, p.y) for p in points]
    for box, oid in obstacles:
        if any(seg_box_dist(pts[i], pts[i + 1], box) < clear
               for i in range(len(pts) - 1)):
            out.append(("node", oid))
    me = Strip(points=pts, half_w=clear)
    exempt_infl = [_inflate(_rect_box(r), clear + 4.0)
                   for r in exempt_rects]
    for s in strips:
        if strip_hits_clip(me, clip_strip(s, exempt_infl)):
            out.append(("strip", s.owner))
    return out






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
    fans, meshes) greedily in declaration order — earlier routed edges'
    anchor slots inform later edges' deliberate offsets (0.26.1)."""
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
    # View-level curation: except pairs drop declared edges before
    # expansion (source, target, type "" = any type).
    except_pairs = {(s, t, ty) for s, t, ty in
                    getattr(select, "except_pairs", []) or []}
    if except_pairs:
        kept = [e for e in model.edges
                if not any((e.source == es and e.target == et
                            and (ty == "" or ty == e.type))
                           for es, et, ty in except_pairs)]
        model = _dc_replace(model, edges=kept)
    _, edges = materialize_instances(select, model)

    # ADR-005: `records: shown` — one bridge edge per recorded node in
    # the view (runtime → record). Synthetic view edges: the records:
    # attribute stays model-level; the bridge is its rendering. Amber,
    # solid, headless — the persistence axis states no call and no
    # pointer (the pointer is the data-model view's FK→PK argument).
    if getattr(select, "show_records", False):
        stack = list(layout.nodes)
        while stack:
            n = stack.pop()
            stack.extend(n.children)
            if n.records and n.records != n.id \
                    and layout.find(n.records) is not None:
                edges.append(Edge(source=n.id, target=n.records,
                                  type="records", arrow="none"))

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
    # Deliberate offsets: chosen anchors' face coordinates, so later
    # edges sharing a face (fans, anti-parallel pairs) prefer distinct
    # ladder slots — offsets, not bends (0.26.1).
    used_anchors: dict = {}

    # Predictable anchor distribution (review round 1): fan members
    # (same source or same target, same dominant face) get evenly
    # spread slots across the face — sorted by the far end's position —
    # and anti-parallel pairs route as parallel strokes symmetric about
    # the face centres (the first edge biases +δ, its reverse mirrors
    # −δ, the U run shifts with them).
    out_fans: dict[str, list] = defaultdict(list)
    in_fans: dict[str, list] = defaultdict(list)
    for it in ordered:
        out_fans[it[0].source].append(it)
        in_fans[it[0].target].append(it)
    edge_hints: dict[int, dict] = {}
    edge_bias: dict[int, float] = {}
    for node_id, members in list(out_fans.items()) + list(in_fans.items()):
        side = "src" if out_fans.get(node_id) is members else "tgt"
        if len(members) < 2:
            continue
        node = members[0][1] if side == "src" else members[0][2]
        rect = node.rect
        face = _dominant_face(rect, members[0][2].rect if side == "src"
                              else members[0][1].rect)
        if any(_dominant_face(m[1].rect if side == "src" else m[2].rect,
                              m[2].rect if side == "src" else m[1].rect)
               != face for m in members):
            continue  # mixed faces: the ladder's own diversity wins
        lo, hi = ((rect.y, rect.y + rect.h) if face in ("right", "left")
                  else (rect.x, rect.x + rect.w))
        usable = hi - lo - 2 * SEED_INSET
        spacing = min(2 * SEED_STEP, usable / (len(members) - 1)) \
            if len(members) > 1 else 0.0
        center = (lo + hi) / 2.0
        key = (lambda m: m[2].rect.cy if side == "src" and face in
               ("right", "left") else
               m[1].rect.cy if face in ("right", "left") else
               m[2].rect.cx if side == "src" else m[1].rect.cx)
        for i, m in enumerate(sorted(members, key=key)):
            delta = (i - (len(members) - 1) / 2.0) * spacing
            edge_hints.setdefault(id(m), {"src": {}, "tgt": {}})[side][face] \
                = center + delta

    anti_parallel: dict = {}
    for it in ordered:
        anti_parallel.setdefault(frozenset((it[0].source, it[0].target)),
                                 []).append(it)
    for group in anti_parallel.values():
        if len(group) == 2 and group[0][0].source == group[1][0].target:
            edge_bias[id(group[0])] = PAIR_BIAS
            edge_bias[id(group[1])] = -PAIR_BIAS

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

        pts, _clear = _route_edge_full(
            src_rect, tgt_rect, obstacles, strips_done, exempt_rects,
            src_anchor, tgt_anchor, src_key=edge.source,
            tgt_key=edge.target, used_anchors=used_anchors,
            label=edge.label,
            hints=edge_hints.get(id((edge, src_node, tgt_node))),
            pair_bias=edge_bias.get(id((edge, src_node, tgt_node))),
            orthogonal=(getattr(select, "routing", "") == "orthogonal"))
        if not pts:
            # Complete search failure (degenerate geometry): fall back
            # to the dominant-face pair so the edge still renders.
            pts = [
                _face_point(src_rect, _dominant_face(src_rect, tgt_rect)),
                _face_point(tgt_rect, _dominant_face(tgt_rect, src_rect)),
            ]

        # Record the final anchors' face coordinates so later edges
        # sharing a face prefer distinct offsets (deliberate, not
        # emergent-from-collision: offsets are not bends).
        a, b = pts[0], pts[-1]
        fs, ft = _nearest_face(src_rect, a), _nearest_face(tgt_rect, b)
        used_anchors.setdefault((edge.source, fs), set()).add(
            _face_coord(a, fs))
        used_anchors.setdefault((edge.target, ft), set()).add(
            _face_coord(b, ft))

        style = _default_style(edge.type)
        strip = _edge_strip(pts, edge)
        residuals = _path_residuals(pts, obstacles, strips_done, clear,
                                   exempt_rects)
        plen = sum(pts[i].distance_to(pts[i + 1])
                   for i in range(len(pts) - 1))
        direct = _border_distance(src_rect, tgt_rect)
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
            direct=direct,
            ratio=plen / max(direct, 1.0),
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
