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
    strips_overlap,
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
PORT_EXCLUSIVE_COST = 400.0  # px — a used face port is closed (ADR-003:
                         # separation is deliberate offsets). Convergent
                         # or divergent edges spread to fresh ladder
                         # slots; a shared port pays exclusion scale,
                         # above every length saving and a bend, so it
                         # survives only when no other candidate exists
                         # (2026-09-21: the old 8px reuse price lost to
                         # the length incentive and three convergent
                         # unit_agent edges stacked onto one arrowhead)
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
# The along-leg shift fracs, shared with the renderer's along-leg
# shift pass — one source of truth (the convention lives in one
# place, not re-typed at each draw site; the recurrence lesson of the
# multi-line label convention applies).
LABEL_SHIFT_FRACS = (0.5, 0.35, 0.65, 0.25, 0.75, 0.15, 0.85,
                     0.92, 0.08, 0.96, 0.04)
HINT_MISS_COST = 18.0    # px — ignoring a fan-slot / pair-bias anchor
                         # hint: hints encode predictable, distributed
                         # anchor points and parallel pair strokes; a
                         # clear hinted route beats an unhinted one
                         # unless the hinted geometry is blocked
HINT_MISS_DECLARED = 30.0  # px — ignoring a DECLARED fan face's ideal
FAN_FACE_HOLD = 100.0     # px — a GROUPED fan's face holds ABOVE the
                          # label costs: the fan's reading is the
                          # structure, a label graze is soft (measured:
                          # app3's east-face route lost to the
                          # bottom-face escape because the east route's
                          # LABEL grazed the neighbouring pod —
                          # LABEL_NODE_COST 80 vs the escape's
                          # discipline 20; the reviewer's rule: the
                          # three apps relate to the controller LIKE A
                          # FAN).
                         # symmetric slot (2026-09-21 reviewer rule:
                         # fan out symmetric about the midpoint, as
                         # close to it as can be): above the length
                         # incentive (measured: a declared cloud pair
                         # drifted to the ladder's k=3 edge on a ~22px
                         # stub saving), under the label costs so a
                         # label-carrying fan can still spread its
                         # slots when its labels demand room
PORT_GAP      = 24.0   # px — max spacing between fan ports on one
                         # face: wide enough that multiple
                         # arrowheads read as deliberate ports,
                         # not jitter (2026-09-19 review)
PAIR_BIAS     = 6.0      # px — the first edge of an anti-parallel pair
                         # biases this far off the face centre; its
                         # reverse mirrors to −bias: two parallel
                         # strokes 12px apart, symmetric about the axis
CENTRE_MISS_COST = 18.0  # px — a deliberate form (L/U) anchoring off
                         # the face centre: arrows start/end in the
                         # middle of an edge; offsets are for fans and
                         # for dodging blocked centres only
FACE_DISCIPLINE_COST = 20  # px — an anchor pair against the port
                         # discipline (ADR-007): inter-column edges
                         # prefer source-EAST/target-WEST, same-column
                         # edges prefer the column axis. Priced under
                         # TURN_PENALTY (40) so it can never buy a
                         # bend — the ADR-003 vocabulary (<=2 bends)
                         # is the hard law, discipline yields to it —
                         # and over the old anchor-reuse price so among
                         # bend-equal candidates the disciplined pair
                         # wins. The label costs (24 per strip hit, 80 per node
                         #  strike) outrank it — 20 sits under 24 by design: a
                         # disciplined face is traded for label corridor before it is
                         # traded for a bend (measured on the refinement
                         # acceptance view — 20 un-dents a fan corner that 12
                         # left; the third fan edge into a shared face keeps its dodge).
                         # ELK precedent: it picks faces per edge the
                         # same way (3/9 EAST entries on Worker tree
                         # machine cloud, 17/17 WEST on Worker tree
                         # controller — geometry, not dogma).
RIDE_COST      = 400.0  # px — a surviving border ride (first/last leg
                         # collinear with a face line; 2026-09-21 hard
                         # law: never permitted). Priced above every
                         # legitimate cost bundle (bends, label strikes,
                         # discipline combined), so any ride-free
                         # candidate wins; a ride survives only when the
                         # alternative is a crossing or no route — and
                         # the audit's border-rides metric gates it.


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
    # Where along the longest leg the label sits (the along-leg shift;
    # 0.5 = the midpoint). The renderer and the audit consume the same
    # frac, so the drawn label and the measured label agree.
    label_anchor: float = 0.5
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
    # ADR-009 bow pairs: a signed apex offset (px, along the chord's
    # world normal) for anti-parallel same-corridor strokes — the
    # "back and forth" pair draws as two shallow mirrored arcs so the
    # strokes AND their labels separate. 0 = the straight vocabulary.
    bow: float = 0.0

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

    def label_score(self, pts, frac=0.5):
        """(node_hits, other_hits) of the label this route would draw
        at `frac` along its longest leg: the label strip vs node rects
        (weight-heavy — nodes are solid) and vs earlier strips'
        corridors, labels and caps."""
        if not self.label:
            return 0, 0
        lg = label_geometry([(p.x, p.y) for p in pts], self.label, frac)
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
        # Both L orientations are generated; one of them has a first or
        # last leg collinear with a face line (a border ride). The
        # evaluator corner-snaps riding endpoints (2026-09-21 hard law:
        # a stroke meets its face perpendicularly or lands at the
        # face-span end — it never rides the border), so the mirror
        # form stays available where it is the only clear corridor.
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
            # Its riding final leg is corner-snapped by the evaluator.
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





def _ride_len(pts, src_rect, tgt_rect):
    """Total px of border ride on the first/last legs (collinear
    overlap with the node's own face line) — the quantity RIDE_COST
    prices and the audit's border-rides metric gates. Straights cannot
    ride (perpendicular crossing or diagonal), so len<3 returns 0."""
    if len(pts) < 3:
        return 0.0
    total = 0.0
    for p_end, p_in, rect in ((pts[0], pts[1], src_rect),
                              (pts[-1], pts[-2], tgt_rect)):
        if abs(p_end.x - p_in.x) < 0.5:          # vertical leg
            if (abs(p_end.x - rect.x) < 0.5
                    or abs(p_end.x - rect.x2) < 0.5):
                ylo, yhi = sorted((p_end.y, p_in.y))
                total += max(0.0, min(yhi, rect.y2) - max(ylo, rect.y))
        elif abs(p_end.y - p_in.y) < 0.5:        # horizontal leg
            if (abs(p_end.y - rect.y) < 0.5
                    or abs(p_end.y - rect.y2) < 0.5):
                xlo, xhi = sorted((p_end.x, p_in.x))
                total += max(0.0, min(xhi, rect.x2) - max(xlo, rect.x))
    return total


SNAP_SKIP = object()  # _corner_snap sentinel: the ride collapse's
# target would leave a set face — drop the candidate form instead of
# landing a multi-edge face off its symmetric port set.


def _leg_rides(pts, src_rect, tgt_rect):
    """Does the first or last leg ride a node border? (2026-09-21 hard
    law: a stroke meets its face perpendicularly — it never runs along
    the border before landing). The pinned candidate path filtered Ls
    directly; the vocabulary loop's free straights/Ls relied on
    _corner_snap, which only fires on >=3-point candidates — a
    STRAIGHT collinear with an endpoint face line slipped through
    until the port sets made it the cheapest clear route."""
    for p_end, p_in, rect in ((pts[0], pts[1], src_rect),
                              (pts[-1], pts[-2], tgt_rect)):
        if abs(p_end.x - p_in.x) < 0.5:      # vertical leg
            if (abs(p_end.x - rect.x) < 0.5
                    or abs(p_end.x - rect.x2) < 0.5):
                ylo, yhi = sorted((p_end.y, p_in.y))
                if min(yhi, rect.y2) - max(ylo, rect.y) > 0.5:
                    return True
        elif abs(p_end.y - p_in.y) < 0.5:    # horizontal leg
            if (abs(p_end.y - rect.y) < 0.5
                    or abs(p_end.y - rect.y2) < 0.5):
                xlo, xhi = sorted((p_end.x, p_in.x))
                if min(xhi, rect.x2) - max(xlo, rect.x) > 0.5:
                    return True
    return False


def _corner_snap(pts, src_rect, tgt_rect, src_set=None, tgt_set=None):
    """Collapse a border ride (2026-09-21 hard law: a stroke meets its
    face perpendicularly — it never runs along the border before
    landing). When a candidate's first or last leg is collinear with
    its own node's face line, the riding endpoint slides to the
    face-span end nearest the penultimate point: the stroke arrives
    from outside and lands at the corner. Returns the (possibly
    point-reduced) pts; None when nothing rode; SNAP_SKIP when the
    collapse target is off a set face's symmetric port set (the
    corner is not a valid anchor there — the honest form is the
    perpendicular L / U from a slot)."""
    pts = list(pts)
    if len(pts) < 3:
        return None
    changed = False
    for i, rect, port_set in ((0, src_rect, src_set),
                              (len(pts) - 1, tgt_rect, tgt_set)):
        p_end = pts[i]
        p_in = pts[1] if i == 0 else pts[-2]
        vertical_leg = abs(p_end.x - p_in.x) < 0.5
        horizontal_leg = abs(p_end.y - p_in.y) < 0.5
        if vertical_leg:
            # collinear with a vertical face line (left/right): the
            # line coordinate is x, the span runs along y
            lines = ((rect.x, rect.y, rect.y2), (rect.x2, rect.y, rect.y2))
            end_v, in_v, fixed_v = p_end.x, p_in.y, p_end.x
        elif horizontal_leg:
            # collinear with a horizontal face line (top/bottom): the
            # line coordinate is y, the span runs along x
            lines = ((rect.y, rect.x, rect.x2), (rect.y2, rect.x, rect.x2))
            end_v, in_v, fixed_v = p_end.y, p_in.x, p_end.y
        else:
            continue
        for coord, lo, hi in lines:
            if abs(end_v - coord) >= 0.5:
                continue
            # the ride is the leg's extent along the free axis
            # (both endpoints) overlapping the face span
            free_end = p_end.y if vertical_leg else p_end.x
            e_lo, e_hi = sorted((free_end, in_v))
            if min(e_hi, hi) - max(e_lo, lo) <= 0.5:
                continue
            new_v = lo if abs(in_v - lo) <= abs(in_v - hi) else hi
            if abs(new_v - free_end) <= 0.5:
                continue
            if port_set is not None:
                # A set face's anchor lives on the symmetric port set:
                # the corner landing is not admissible. Land on the
                # nearest slot when the ride is that close; otherwise
                # drop the candidate (SNAP_SKIP) — the ride cannot be
                # resolved at an admissible anchor.
                nv = min(port_set, key=lambda v: abs(v - new_v))
                if abs(nv - new_v) <= 0.5:
                    new_v = nv
                else:
                    return SNAP_SKIP
            if vertical_leg:
                pts[i] = Point(fixed_v, new_v)
            else:
                pts[i] = Point(new_v, fixed_v)
            changed = True
            break
    if not changed:
        return None
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p.x - out[-1].x) > 1e-9 or abs(p.y - out[-1].y) > 1e-9:
            out.append(p)
    return out


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
    pref: tuple[str, str] | None = None,
    port_sets: dict | None = None,
):
    """Evaluate every vocabulary candidate. Returns (best_clear,
    best_soft): each is (points, bends, cost, order, crossings) or
    None. cost = length + TURN_PENALTY*bends + anchor reuse + label
    costs + hint misses; `order` makes selection fully deterministic.
    Soft = fewest node crossings, then cheapest — reported, never
    hidden. hints: predictable anchor coordinates per (side, face)
    (fan slots, mirrored pair strokes); pair_bias: symmetric
    off-centre bias for the first edge of an anti-parallel pair;
    orthogonal: reject diagonal legs (declared orthogonal views).
    port_sets: {node_id: {face: sorted coords}} — the symmetric port
    sets of multi-edge faces. For set faces the ONLY admissible
    source/target anchors are the set points: the ladder is replaced
    by the set, and the ride-collapse may land only ON a set slot."""
    best_clear = None   # (points, bends, cost, order, ())
    best_soft = None    # (points, bends, cost, order, crossings)
    hints = hints or {}

    # Port discipline (ADR-007): the preferred (exit, enter) faces for
    # this pair's geometry — inter-column: source-EAST/target-WEST on
    # a rightward flow (mirrored leftward); same-column: along the
    # column axis. A cost *preference*: priced under TURN_PENALTY, so
    # a bend never gets added to satisfy it, and the U-shape
    # (chain-skip over an align-middle blocker) keeps its two bends.
    # A DECLARED fan face (pref — from the view's FanConstraint via
    # SolvedLayout.fan_faces) overrides the geometric class entirely:
    # "fan above" means the anchor's arrows leave north whatever the
    # fan's spread does to the centre deltas (measured: a wide uniform
    # fan above misread as inter-column flow and the arrows left
    # west/east until the declaration spoke).
    dx_c = ((tgt_rect.x + tgt_rect.w / 2.0)
            - (src_rect.x + src_rect.w / 2.0))
    dy_c = ((tgt_rect.y + tgt_rect.h / 2.0)
            - (src_rect.y + src_rect.h / 2.0))
    if pref is not None:
        preferred = pref
    elif abs(dx_c) >= abs(dy_c):
        preferred = ("right", "left") if dx_c > 0 else ("left", "right")
    else:
        preferred = (("bottom", "top") if dy_c > 0
                     else ("top", "bottom"))

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
                        snapped = _corner_snap(
                            pts, src_rect, tgt_rect,
                            src_set=port_sets.get(src_key, {}).get(fs)
                            if port_sets else None,
                            tgt_set=port_sets.get(tgt_key, {}).get(ft)
                            if port_sets else None)
                        if snapped is SNAP_SKIP:
                            continue
                        if snapped is not None:
                            pts = snapped
                        if _leg_rides(pts, src_rect, tgt_rect):
                            continue
                        reuse = 0.0
                        if used_anchors is not None and not pinned:
                            # Keyed by (node, face) regardless of edge
                            # role: an anti-parallel pair's reverse
                            # edge must see the forward edge's slots.
                            # A used port is CLOSED (ADR-003: offsets
                            # are deliberate; 2026-09-21 fan review:
                            # an 8px reuse price lost to the length
                            # incentive and convergent edges stacked
                            # onto one arrowhead — the unpacked view's
                            # three unit_agent edges shared one west-
                            # face port). Exclusion scale: a fresh
                            # ladder slot wins over any length saving;
                            # a shared port survives only when no
                            # other candidate exists.
                            if _face_coord(a, fs) in used_anchors.get(
                                    (src_key, fs), ()):
                                reuse += PORT_EXCLUSIVE_COST
                            if _face_coord(b, ft) in used_anchors.get(
                                    (tgt_key, ft), ()):
                                reuse += PORT_EXCLUSIVE_COST
                        cost = direct + TURN_PENALTY * bends + reuse
                        if (fs, ft) != preferred:
                            cost += FACE_DISCIPLINE_COST
                            # A DECLARED fan's faces are content: an
                            # off-face escape evades the per-face hint
                            # miss (the hint is keyed to the declared
                            # face) and would otherwise pay only the
                            # flat discipline price — measured: the
                            # refined cloud pair escaped to the west
                            # face's bottom corner because the
                            # corner-to-corner diagonal was 28px
                            # shorter. The declared scale holds the
                            # faces; the member/hub slot hints then
                            # distribute within them.
                            if (hints.get("declared_src")
                                    or hints.get("declared_tgt")):
                                cost += HINT_MISS_DECLARED
                            if (hints.get("fan_held_src")
                                    or hints.get("fan_held_tgt")):
                                cost += FAN_FACE_HOLD
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
                        # A DECLARED fan face holds harder: the view
                        # spoke, and the ideal symmetric slots must
                        # beat a stub's length saving (measured: the
                        # declared cloud pair drifted to the ladder's
                        # k=3 edge because the soft price lost to
                        # ~22px) — while staying under the label
                        # costs, so a label-carrying fan can still
                        # spread beyond the ideal slots when its
                        # labels demand room.
                        # The declared price holds only the HUB face
                        # (the view's declaration is about where the
                        # fan attaches); the member side stays soft so
                        # a label-carrying member can still spread off
                        # its centre when its label demands room
                        # (measured: cloud_b's centre entry rode app1's
                        # label strip — the off-centre slot is the
                        # honest fix).
                        if hints.get("declared_src"):
                            src_price = HINT_MISS_DECLARED
                        else:
                            src_price = HINT_MISS_COST
                        if hints.get("declared_tgt"):
                            tgt_price = HINT_MISS_DECLARED
                        else:
                            tgt_price = HINT_MISS_COST
                        sh = hints.get("src", {}).get(fs)
                        if sh is not None and \
                                abs(_face_coord(a, fs) - sh) > 0.5:
                            cost += src_price
                        th = hints.get("tgt", {}).get(ft)
                        if th is not None and \
                                abs(_face_coord(b, ft) - th) > 0.5:
                            cost += tgt_price
                        if pair_bias is not None:
                            ba = abs(_face_coord(a, fs)
                                     - (_center(src_rect, fs) + pair_bias))
                            bb = abs(_face_coord(b, ft)
                                     - (_center(tgt_rect, ft) + pair_bias))
                            if ba > 0.5 or bb > 0.5:
                                cost += HINT_MISS_COST
                        if _ride_len(pts, src_rect, tgt_rect) > 0.5:
                            cost += RIDE_COST
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
    pref: tuple[str, str] | None = None,
    port_sets: dict | None = None,
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
                hints=hints, pair_bias=pair_bias, orthogonal=orthogonal,
                pref=pref)
    else:
        src_ladder = _anchor_ladder(src_rect)
        tgt_ladder = _anchor_ladder(tgt_rect)
        # Fan hints are REAL candidate anchors: the ideal symmetric
        # slots (centre ± spacing/2 about the face midpoint) usually
        # sit between ladder slots, so as mere preferences they were
        # no-ops — every candidate paid HINT_MISS equally. Insert the
        # hinted coordinate into the face's ladder so the slot exists.
        for ladder, rect in ((src_ladder, src_rect),
                             (tgt_ladder, tgt_rect)):
            side = "src" if ladder is src_ladder else "tgt"
            for face, coord in ((hints or {}).get(side, {}) or {}).items():
                slots = ladder.get(face)
                if not slots:
                    continue
                if any(abs(_face_coord(p, face) - coord) < 0.5
                       for p in slots):
                    continue
                on_width = face in ("top", "bottom")
                px = coord if on_width else (
                    _snap(rect.x) if face == "left" else _snap(rect.x2))
                py = (_snap(rect.y) if face == "top"
                      else _snap(rect.y2)) if on_width else coord
                slots.append(Point(px, py))
                slots.sort(key=lambda p: _face_coord(p, face))
        base_src = {f: list(v) for f, v in src_ladder.items()}
        base_tgt = {f: list(v) for f, v in tgt_ladder.items()}
        if port_sets:
            for ladder, key, rect in ((src_ladder, src_key, src_rect),
                                      (tgt_ladder, tgt_key, tgt_rect)):
                for face in list(ladder):
                    slots = port_sets.get(key, {}).get(face)
                    if not slots:
                        continue
                    on_width = face in ("top", "bottom")
                    pts = []
                    for v in slots:
                        if face == "right":
                            pts.append(Point(_snap(rect.x2), v))
                        elif face == "left":
                            pts.append(Point(_snap(rect.x), v))
                        elif face == "top":
                            pts.append(Point(v, _snap(rect.y)))
                        else:
                            pts.append(Point(v, _snap(rect.y2)))
                    ladder[face] = pts
            best_clear, best_soft = _route_candidates_eval(
                src_rect, tgt_rect, src_ladder, tgt_ladder, search,
                src_key, tgt_key, used_anchors,
                hints=hints, pair_bias=pair_bias, orthogonal=orthogonal,
                pref=pref, port_sets=port_sets)
            if best_clear is None and (soft or best_soft is None):
                # No set-anchored candidate exists (dense geometry):
                # retry unrestricted — the corner landing the hard law
                # sanctions — so a border ride is never forced; the
                # audit measures the set-miss instead.
                src_ladder, tgt_ladder = base_src, base_tgt
                best_clear, best_soft = _route_candidates_eval(
                    src_rect, tgt_rect, src_ladder, tgt_ladder, search,
                    src_key, tgt_key, used_anchors,
                    hints=hints, pair_bias=pair_bias,
                    orthogonal=orthogonal, pref=pref, port_sets=None)
        else:
            best_clear, best_soft = _route_candidates_eval(
                src_rect, tgt_rect, src_ladder, tgt_ladder, search,
                src_key, tgt_key, used_anchors,
                hints=hints, pair_bias=pair_bias, orthogonal=orthogonal,
                pref=pref, port_sets=None)

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
    # Perpendicularity (2026-09-21, hard law — no border grazing): an L
    # whose first or last leg is collinear with a face line rides the
    # node border before meeting the face. Tested directly (corner
    # anchors make nearest-face classification ambiguous); only
    # ride-free orientations are kept.
    for cand in ([a, Point(b.x, a.y), b], [a, Point(a.x, b.y), b]):
        if not _leg_rides(cand, src_rect, tgt_rect):
            forms.append((cand, 1))
    if not forms and orthogonal:
        # The vocabulary cannot express this pair orthogonally without
        # riding (same-facing or same-axis faces, misaligned rows).
        # A diagonal beats a border ride.
        forms.append(([a, b], 0))
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

def _edge_strip(points, edge, bow: float = 0.0, owner: str = "") -> Strip:
    pts = [(p.x, p.y) for p in points]
    if not owner:
        src = getattr(edge, "source", None) or getattr(edge, "source_id", "?")
        tgt = getattr(edge, "target", None) or getattr(edge, "target_id", "?")
        owner = f"{src}->{tgt}"
    return strip_for_edge(pts, ROUTE_STROKE_W, edge.arrow, edge.label,
                          0.5, owner=owner, bow=bow)


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


def _port_sets(ordered, layout, fan_faces, pair_biased):
    """Symmetric port sets for every multi-edge face (>=2 edges
    touching one face, any direction): the anchors distribute about
    the face midpoint — mid ± (2i+1)*d/2 (even count) or mid ± i*d
    (odd), d = min(PORT_GAP, usable/(n-1)); a same-pair anti-parallel
    keeps its pair-bias mirrors (mid ± PAIR_BIAS — itself a symmetric
    distribution, already calibrated for its label corridor).

    The axis (the face midpoint) is ALWAYS a member: a spine/align
    edge holds the row axis (the straightest line), and the fan/peer
    edges distribute about it at the symmetric slots (measured: the
    worker-tree machine-cloud column tilted when the axis seat was
    excluded — an align-middle arrow must stay straight).

    Returns {node_id: {face: tuple(sorted coords)}}. The face of each
    end is the geometric dominant face (declared fan faces override).
    The router restricts set faces' candidates to these points; a
    face whose edges end up elsewhere lands no set and the audit
    measures the miss."""
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for edge, src_node, tgt_node in ordered:
        if (edge.source, edge.target) in fan_faces:
            # declared fan: the author's face/spacing owns the ports
            continue
        declared = fan_faces.get((edge.source, edge.target))
        for end, nid, mine, other in (
                ("src", edge.source, src_node, tgt_node),
                ("tgt", edge.target, tgt_node, src_node)):
            face = (declared[0] if declared else None) if end == "src" \
                else (declared[1] if declared else None)
            if face is None:
                face = _dominant_face(mine.rect, other.rect)
            groups[(nid, face)].append(edge)
    out: dict[str, dict[str, tuple]] = {}
    for (nid, face), edges in groups.items():
        if len(edges) < 2:
            continue
        node = layout.find(nid)
        if node is None:
            continue
        r = node.rect
        on_width = face in ("top", "bottom")
        lo, hi = ((r.x, r.x + r.w) if on_width
                  else (r.y, r.y + r.h))
        center = (lo + hi) / 2.0
        usable = hi - lo - 2 * SEED_INSET
        pair_edges = [e for e in edges if id(e) in pair_biased]
        pair_same = (len(edges) == 2 and len(pair_edges) == 2
                     and pair_edges[0].source == pair_edges[1].target
                     and pair_edges[0].target == pair_edges[1].source)
        if pair_same:
            d = PAIR_BIAS * 2.0
        else:
            d = min(PORT_GAP, usable / (len(edges) - 1))
            if d < 1.0:
                d = 1.0
        slots = [center]
        if len(edges) % 2 == 1:
            for i in range(1, len(edges) // 2 + 1):
                slots.append(center - i * d)
                slots.append(center + i * d)
        else:
            for i in range(len(edges) // 2):
                slots.append(center - (2 * i + 1) * d / 2.0)
                slots.append(center + (2 * i + 1) * d / 2.0)
        vals = []
        for v in slots:
            v = min(max(_snap(v), lo + SEED_INSET), hi - SEED_INSET)
            if all(abs(v - u) > 1e-9 for u in vals):
                vals.append(v)
        if len(vals) < 2:
            continue
        out.setdefault(nid, {})[face] = tuple(sorted(vals))
    return out


def route(layout: SolvedLayout, model: Model, select) -> RoutedLayout:
    """Compute routed edges for all model edges whose endpoints are in layout."""
    # ADR-006: an ELK-laid-out view carries its edge geometry from the
    # backend — wrap it (strips for the label contract, audit metrics
    # computed the same way as built-in routes) and skip the router.
    # Routes are matched against the MATERIALIZED edges: instance
    # expansion rewires endpoints (user -> bare_application becomes
    # user -> app1/2/3), so the raw model edges don't carry the
    # expanded endpoint ids.
    if getattr(layout, "edge_routes", None):
        _, mat_edges = materialize_instances(select, model)
        by_id = {n.id: n for n in layout.nodes}
        routed_edges = []
        for src, tgt, pts in layout.edge_routes:
            e = next((x for x in mat_edges
                      if x.source == src and x.target == tgt), None)
            if e is None or src not in by_id or tgt not in by_id:
                continue
            strip = _edge_strip(pts, e)
            plen = sum(pts[i].distance_to(pts[i + 1])
                       for i in range(len(pts) - 1))
            direct = _border_distance(by_id[src].rect, by_id[tgt].rect)
            # Nested endpoints (an edge inside its own container, or
            # container-to-child): border distance is 0 and the
            # traceability ratio is meaningless — record 1.0 rather
            # than a phantom >2x defect (measured: a 16px internal
            # edge in principles' IAAS chain gated as a 16x monster).
            if direct < 1.0:
                direct = plen
            routed_edges.append(RoutedEdge(
                source_id=src, target_id=tgt, label=e.label,
                edge_type=e.type, style=e.style if e.style else _default_style(e.type),
                arrow=e.arrow, url=e.url, points=pts,
                turns=_count_turns([(p.x, p.y) for p in pts]), residuals=[],
                direct=direct, ratio=plen / max(direct, 1.0), strip=strip))
        _assign_bows(routed_edges, layout)
        return RoutedLayout(layout=layout, edges=routed_edges)

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
    if getattr(select, "hide_labels", False):
        # "labels: hidden" (2026-09-22 reviewer: the excalidraw teaching
        # diagrams were lighter because their arrows carried no
        # labels): the view mutes every edge label BEFORE routing —
        # the router prices label-free corridors, so the suppressed
        # labels never reserve width. The model keeps its labels;
        # other views keep theirs. The muting REPLACES the edge
        # objects (materialize hands out the model's own Edge
        # references — mutating them in place leaked the blank into
        # every later view and flipped their solves; measured: the
        # worker-synth view detoured at 2.47x once the tutorial
        # views' blanking ran first).
        edges = [_dc_replace(e, label="") for e in edges]

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

    # Top-level id set + parent map: the member-side hint resolves a
    # nested member's CONTAINER (the fan member node), so the align-
    # middle member's arrow anchors at the container's face midpoint —
    # the container's row is what aligns with the hub (the declared
    # fan/typed-hub statements are top-level), not the child's own
    # centre, which the label band pushes ~12px low (measured: app2's
    # arrow left its child's face at container+12 and came in at a NW
    # angle while its hub port sat exactly at the midpoint).
    _top_ids = {n.id for n in layout.nodes}
    _parent_of: dict[str, str] = {}
    _stk = [(n, None) for n in layout.nodes]
    while _stk:
        _n, _p = _stk.pop()
        if _p is not None:
            _parent_of[_n.id] = _p
        for _c in _n.children:
            _stk.append((_c, _n.id))

    def _top_rect(nid: str):
        cur = nid
        while cur not in _top_ids:
            cur = _parent_of.get(cur)
            if cur is None:
                return None
        n = layout.find(cur)
        return n.rect if n is not None else None

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
    # Declared fan faces (from the view's FanConstraints, threaded via
    # SolvedLayout.fan_faces): "fan above" MEANS the anchor's arrows
    # leave north and arrive on the members' south faces. The declared
    # face outranks the geometric dominant-face guess and the
    # centre-delta discipline class — a wide fan above reads as
    # inter-column flow to the centre heuristic (measured: the Juju
    # enters arrows left west/east until the declaration spoke).
    fan_faces = getattr(layout, "fan_faces", {}) or {}
    edge_hints: dict[int, dict] = {}
    edge_bias: dict[int, float] = {}
    anti_parallel: dict = {}
    for it in ordered:
        anti_parallel.setdefault(frozenset((it[0].source, it[0].target)),
                                 []).append(it)
    pair_biased: set[int] = set()
    for group in anti_parallel.values():
        if len(group) == 2 and group[0][0].source == group[1][0].target:
            edge_bias[id(group[0][0])] = PAIR_BIAS
            edge_bias[id(group[1][0])] = -PAIR_BIAS
            pair_biased.add(id(group[0][0]))
            pair_biased.add(id(group[1][0]))
    for node_id, members in list(out_fans.items()) + list(in_fans.items()):
        side = "src" if out_fans.get(node_id) is members else "tgt"
        if len(members) < 2:
            continue
        node = members[0][1] if side == "src" else members[0][2]
        rect = node.rect
        # Group the fan by face — declared where a FanConstraint speaks
        # for the edge, geometric dominant-face otherwise — then
        # distribute each same-face group across that face. (Mixed-face
        # fans used to skip hinting entirely — "the ladder's own
        # diversity wins" — which threw away the same-face subgroup's
        # slots: the Juju enters controller fans two edges out of
        # mid-north and one out of mid-south; a fan from mid-north is
        # the vocabulary's own statement, not a ladder accident.)
        by_face: dict = defaultdict(list)
        for m in members:
            other = m[2].rect if side == "src" else m[1].rect
            mine = m[1].rect if side == "src" else m[2].rect
            declared = fan_faces.get((m[0].source, m[0].target))
            face = (declared[0] if side == "src" else declared[1]) \
                if declared else _dominant_face(mine, other)
            by_face[face].append(m)
        for face, ms in by_face.items():
            if len(ms) < 2:
                continue
            lo, hi = ((rect.y, rect.y + rect.h)
                      if face in ("right", "left")
                      else (rect.x, rect.x + rect.w))
            usable = hi - lo - 2 * SEED_INSET
            spacing = min(PORT_GAP, usable / (len(ms) - 1)) \
                if len(ms) > 1 else 0.0
            center = (lo + hi) / 2.0
            key = (lambda m: m[2].rect.cy if side == "src" and face in
                   ("right", "left") else
                   m[1].rect.cy if face in ("right", "left") else
                   m[2].rect.cx if side == "src" else m[1].rect.cx)
            # The ideal slots are the SYMMETRIC, minimal separation:
            # centre ± k*spacing/2 about the face midpoint (2026-09-21
            # reviewer rule: fan out symmetric about the midpoint and
            # as close to it as can be — better content/white-space
            # distribution than ladder-reach staggering). These are
            # injected as real candidate anchors (see _route_edge_full):
            # the old ladder snap placed ideal ±12 at the ladder's k=3
            # edge (±46), and the length incentive confirmed it.
            for i, m in enumerate(sorted(ms, key=key)):
                # Recompute per member: the grouping loop's `declared`
                # leaks its last iteration's value (an undeclared
                # sibling edge) into this loop — the declared hint
                # price and member-face choice would silently miss.
                m_declared = fan_faces.get((m[0].source, m[0].target))
                ideal = center + (i - (len(ms) - 1) / 2.0) * spacing
                # Keep the ladder's label-calibrated mark: the author's
                # fan spacing was calibrated against label separation
                # at the ladder's slots, so an ideal within a few px of
                # one IS that slot (the refined cloud pair's stubs are
                # label-clean at ±15.33 and strike their neighbour at
                # ±12 — measured, tests/test_refinement).
                step = max(SEED_STEP, usable / 6.0)
                k = round((ideal - center) / step)
                ladder_ideal = center + k * step
                if abs(ladder_ideal - ideal) <= 5.0:
                    ideal = ladder_ideal
                # Key by the edge object's identity, not id() of the
                # (edge, src, tgt) tuple: the lookup rebuilds that
                # tuple, and a fresh tuple's id never matches the
                # stored one — the fan slots were dead code (fans
                # distributed via anchor reuse instead, which is why
                # nobody noticed).
                edge_hints.setdefault(
                    id(m[0]), {"src": {}, "tgt": {}})[side][face] \
                    = ideal
                # A same-face group of >=2 members is a FAN: the face
                # holds against off-face escapes (the label costs
                # yield; see FAN_FACE_HOLD).
                if len(ms) >= 2:
                    edge_hints[id(m[0])]["fan_held_" + side] = True
                # MEMBER side (2026-09-21 reviewer rule, generalized:
                # ANY fan distributes around the edge midpoint — both
                # ends): each member's own face anchors at its centre,
                # so the middle member's arrow is align-middle'ed with
                # the hub (horizontal for a row fan) and the outer
                # members mirror. Without it the member side was pure
                # cost, and convergent arrows hit their nodes off the
                # midpoint (measured: app2's arrow left its west face
                # 15px low). The member centre IS the ladder's k=0
                # slot, so the anchor exists; this hint prices it.
                member = m[1] if side == "tgt" else m[2]
                mrect = member.rect
                if side == "tgt":
                    mface = (m_declared[0] if m_declared
                             else _dominant_face(mrect, rect))
                else:
                    mface = (m_declared[1] if m_declared
                             else _dominant_face(mrect, rect))
                mlo, mhi = ((mrect.x, mrect.x + mrect.w)
                            if mface in ("top", "bottom")
                            else (mrect.y, mrect.y + mrect.h))
                if id(m[0]) not in pair_biased:
                    # An anti-parallel pair's member side is owned by
                    # the pair bias (both strokes straddle the midpoint
                    # at ±PAIR_BIAS — itself a symmetric distribution);
                    # a centre hint here would fight the mirror.
                    # A NESTED align-middle member anchors at its
                    # CONTAINER's face midpoint instead of the child's
                    # own centre: the fan statements are top-level, so
                    # the container's row is what aligns with the hub
                    # (2026-09-21: app2's arrow must be align-middle'ed
                    # with the controller as a whole). Only when the
                    # container's coordinate lies on the child's face;
                    # outer members and top-level members keep the
                    # member's own centre.
                    hint_v = (mlo + mhi) / 2.0
                    if (i == (len(ms) - 1) // 2
                            and member.id not in _top_ids):
                        trect = _top_rect(member.id)
                        if trect is not None:
                            tlo, thi = (
                                (trect.x, trect.x + trect.w)
                                if mface in ("top", "bottom")
                                else (trect.y, trect.y + trect.h))
                            tmid = (tlo + thi) / 2.0
                            if mlo <= tmid <= mhi:
                                hint_v = tmid
                    edge_hints[id(m[0])][
                        "src" if side == "tgt" else "tgt"][mface] = hint_v
                if m_declared:
                    # A declared fan face holds its hint against the
                    # length incentive (2026-09-21 reviewer rule: fan
                    # out symmetric about the midpoint and as close to
                    # it as can be — the declared cloud pair drifted to
                    # the ladder's k=3 edge, ±46, because the ±12 stubs
                    # cost ~22px more than the soft hint price). The
                    # hint stays soft so the router can still spread
                    # label-carrying fans beyond the ideal slots when
                    # the label costs demand it.
                    edge_hints[id(m[0])]["declared_" + side] = True

    # The symmetric-port rule excludes edges under a DECLARED fan
    # constraint (ADR-007: their placement is the author's fan
    # declaration — the declared spacing and the measured label-clean
    # stubs outrank the generic PORT_GAP pitch; measured: the refined
    # cloud pair clashed when the set re-pinned the hub slots).
    # Undeclared fans (the full spine's corner stack) keep the rule.
    port_sets = _port_sets(ordered, layout, fan_faces, pair_biased)
    # Expose to the audit/gate: the symmetric-port rule's measurement
    # must see the sets the router enforced.
    layout.port_sets = port_sets

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
            hints=edge_hints.get(id(edge)),
            pref=(fan_faces.get((edge.source, edge.target))
                  if fan_faces else None),
            pair_bias=edge_bias.get(id(edge)),
            orthogonal=(getattr(select, "routing", "") == "orthogonal"),
            port_sets=port_sets)
        if edge.label and port_sets and pts:
            # Label-aware escape (the rule's "as close as can be"):
            # the set is the tightest symmetric spread; when the
            # set-bound result's label strip CLASHES an earlier label
            # strip (labels NEVER overlap), retry unrestricted and
            # keep the clash-free result — the wider spread stays
            # symmetric about the face midpoint, so the gate still
            # counts it principled.
            lb = getattr(_edge_strip(pts, edge), "label", None)
            clash = (lb is not None and any(
                getattr(es, "label", None) is not None
                and rects_overlap(lb, es.label)
                for es in strips_done))
            if clash:
                try_pts, _try_clear = _route_edge_full(
                    src_rect, tgt_rect, obstacles, strips_done,
                    exempt_rects, src_anchor, tgt_anchor,
                    src_key=edge.source, tgt_key=edge.target,
                    used_anchors=used_anchors, label=edge.label,
                    hints=edge_hints.get(id(edge)),
                    pref=(fan_faces.get((edge.source, edge.target))
                          if fan_faces else None),
                    pair_bias=edge_bias.get(id(edge)),
                    orthogonal=(getattr(select, "routing", "")
                                == "orthogonal"),
                    port_sets=None)
                if try_pts:
                    tlb = getattr(_edge_strip(try_pts, edge), "label",
                                  None)
                    if tlb is None or not any(
                            getattr(es, "label", None) is not None
                            and rects_overlap(tlb, es.label)
                            for es in strips_done):
                        pts = try_pts
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
        # Nested endpoints: border distance is 0 and the traceability
        # ratio is meaningless (a 16px internal edge gated as a 16x
        # monster) — record the path length instead.
        if direct < 1.0:
            direct = plen
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

    _assign_bows(routed_edges, layout)
    return RoutedLayout(layout=layout, edges=routed_edges)


BOW_OFFSET   = 8.0  # px — the apex offset of a bowed corridor pair
BOW_MAX_DIST = 30.0  # px — max perpendicular distance between paired chords


def _assign_bows(edges, layout) -> None:
    """ADR-009 bow pairs: anti-parallel straight strokes that share a
    corridor (nearly parallel, overlapping, within BOW_MAX_DIST) draw
    as two shallow mirrored arcs — the strokes separate AND each label
    rides its own arc's outer side, so the back-and-forth pair reads
    as two lanes instead of one overprinted stroke.

    The axis member stays straight: when exactly one chord is already
    dead straight and the other is not, only the sloped one bows (the
    straight chord is a spine/align seat — an align-middle arrow must
    stay straight, the worker-tree lesson)."""
    straight = [e for e in edges
                if len(e.points) == 2 and e.source_id != e.target_id]
    info = []
    for e in straight:
        (x0, y0), (x1, y1) = ((e.points[0].x, e.points[0].y),
                              (e.points[1].x, e.points[1].y))
        dx, dy = x1 - x0, y1 - y0
        leg = math.hypot(dx, dy)
        if leg < 1:
            continue
        info.append((e, (x0, y0), (x1, y1),
                     (dx / leg, dy / leg), leg,
                     (dy / leg, -dx / leg), abs(dy) < 0.5, abs(dx) < 0.5))
    done: set[int] = set()
    for i in range(len(info)):
        e1, p0a, p1a, d1, l1, n1, flat1, _ = info[i]
        if id(e1) in done:
            continue
        for j in range(i + 1, len(info)):
            e2, p0b, p1b, d2, l2, n2, flat2, _ = info[j]
            if id(e2) in done:
                continue
            if d1[0] * d2[0] + d1[1] * d2[1] > -0.99:
                continue  # not anti-parallel
            # Perpendicular distance of e2's midpoint from e1's line.
            t = ((p0b[0] - p0a[0]) * n1[0]
                 + (p0b[1] - p0a[1]) * n1[1])
            if abs(t) > BOW_MAX_DIST:
                continue
            # Chord projections along d1 must overlap. e2 runs
            # ANTI-parallel: its projection goes backwards along d1 —
            # the interval is [s0 - l2, s0] (measured: the machine
            # designations pair's chords touch at the controller face
            # and the naive forward interval rejected the overlap).
            s0 = (p0b[0] - p0a[0]) * d1[0] + (p0b[1] - p0a[1]) * d1[1]
            end = s0 + (d2[0] * d1[0] + d2[1] * d1[1]) * l2
            lo, hi = (s0, end) if s0 <= end else (end, s0)
            if min(hi, l1) - max(lo, 0.0) < 0.5 * min(l1, l2):
                continue
            # Away directions: from the other edge's line outward.
            away2 = (t / abs(t) if t else 1.0) * n1[0], \
                    (t / abs(t) if t else 1.0) * n1[1]
            t2 = ((p0a[0] - p0b[0]) * n2[0]
                  + (p0a[1] - p0b[1]) * n2[1])
            away1 = (t2 / abs(t2) if t2 else 1.0) * n2[0], \
                    (t2 / abs(t2) if t2 else 1.0) * n2[1]
            if flat1 and not flat2:
                e2.bow = BOW_OFFSET * _towards(away2, n2)
            elif flat2 and not flat1:
                e1.bow = BOW_OFFSET * _towards(away1, n1)
            else:
                e1.bow = BOW_OFFSET * _towards(away1, n1)
                e2.bow = BOW_OFFSET * _towards(away2, n2)
            # Safety veto: keep a bow only when its rebuilt strip —
            # label + corridor — stays clear of every node box that is
            # not the edge's own endpoint (measured: the Agent
            # taxonomy's controller<->containeragent corridor passes
            # OVER the middle row; bowing its labels onto those nodes
            # manufactures strikes. The straight vocabulary stays when
            # the bow cannot pay for itself).
            ok = True
            for e in (e1, e2):
                if not e.bow:
                    continue
                e.strip = _edge_strip(
                    e.points, e, bow=e.bow,
                    owner=f"{e.source_id}->{e.target_id}")
                # Corridor veto: the bowed sweep must not overlap any
                # OTHER edge's swept strip (measured: the Agent
                # taxonomy's half-bowed corridor pair swept into
                # controller->containeragent's strip — two SCROSSes).
                half = ROUTE_STROKE_W / 2.0 + 2.0
                for o in edges:
                    if o is e1 or o is e2 or o.strip is None:
                        continue
                    opt = [(p[0], p[1]) for p in o.strip.points]
                    swept = [(p[0], p[1]) for p in e.strip.points]
                    hit = False
                    for i in range(len(swept) - 1):
                        for j in range(len(opt) - 1):
                            a, b = swept[i], swept[i + 1]
                            c0, c1 = opt[j], opt[j + 1]
                            if (_seg_dist(a, b, c0, c1)
                                    < half + o.strip.half_w):
                                hit = True
                                break
                        if hit:
                            break
                    if hit:
                        e.bow = 0.0
                        e.strip = _edge_strip(
                            e.points, e,
                            owner=f"{e.source_id}->{e.target_id}")
                        break
                src_box = _member_rect(layout, e.source_id)
                tgt_box = _member_rect(layout, e.target_id)
                if e.strip.label is not None:
                    for n in _layout_rects(layout):
                        box = (n.rect.x, n.rect.y,
                               n.rect.x + n.rect.w, n.rect.y + n.rect.h)
                        if (src_box and _rect_contains(src_box, box)) \
                                or (tgt_box and _rect_contains(tgt_box, box)):
                            continue
                        # A label over the endpoint's own CONTAINER is
                        # by design too (the box wraps the endpoint's
                        # corridor) — exempt ancestors of the members.
                        if (src_box and _rect_contains(box, src_box)) \
                                or (tgt_box and _rect_contains(box, tgt_box)):
                            continue
                        if rects_overlap(e.strip.label, box):
                            e.bow = 0.0
                            e.strip = _edge_strip(
                                e.points, e,
                                owner=f"{e.source_id}->{e.target_id}")
                            break
                if not e.bow:
                    ok = False
            if not ok:
                # Either member vetoed: revert both to the straight
                # vocabulary — a half-bowed pair is worse than none.
                e1.bow = e2.bow = 0.0
                e1.strip = _edge_strip(
                    e1.points, e1, owner=f"{e1.source_id}->{e1.target_id}")
                e2.strip = _edge_strip(
                    e2.points, e2, owner=f"{e2.source_id}->{e2.target_id}")
            done.update((id(e1), id(e2)))
            break


def _towards(away, normal) -> float:
    """+1 when the away direction matches the chord normal's sign."""
    return 1.0 if away[0] * normal[0] + away[1] * normal[1] >= 0 else -1.0



def _member_rect(layout, node_id):
    n = layout.find(node_id)
    if n is None:
        return None
    r = n.rect
    return (r.x, r.y, r.x + r.w, r.y + r.h)


def _layout_rects(layout):
    out = []
    stack = list(layout.nodes)
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(n.children)
    return out


def _rect_contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and outer[2] >= inner[2] and outer[3] >= inner[3])



def _seg_dist(a, b, c, d):
    """Minimum distance between segments ab and cd (dense sampling —
    the veto runs over a handful of candidate pairs, not the corpus)."""
    best = float("inf")
    n = 8
    for i in range(n + 1):
        t = i / n
        px = a[0] + (b[0] - a[0]) * t / n
        py = a[1] + (b[1] - a[1]) * t / n
        for j in range(n + 1):
            qx = c[0] + (d[0] - c[0]) * j / n
            qy = c[1] + (d[1] - c[1]) * j / n
            dd = math.hypot(px - qx, py - qy)
            if dd < best:
                best = dd
    return best


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
