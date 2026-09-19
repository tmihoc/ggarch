"""Strip geometry tests — the swept collision currency (ADR-003).

A strip is the swept corridor of a routed edge: path + stroke width +
arrowhead + the one-sided ADR-002 label extent. These tests pin the
intersection semantics the router, solver and audit all share through
ggarch.geometry (the label_geometry precedent: one module, imported
everywhere, never replicated).
"""
from ggarch.geometry import (
    ARROWHEAD_SIZE,
    Strip,
    point_box_dist,
    seg_box_dist,
    seg_seg_dist,
    strip_for_edge,
    strips_overlap,
)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

class TestPrimitives:
    def test_point_inside_box_is_zero(self):
        assert point_box_dist((5, 5), (0, 0, 10, 10)) == 0.0

    def test_point_outside_box(self):
        assert abs(point_box_dist((15, 5), (0, 0, 10, 10)) - 5.0) < 1e-9

    def test_seg_box_dist_clear_pass(self):
        # A horizontal stroke 10px below the box: distance 10.
        assert abs(seg_box_dist((0, 20), (40, 20), (0, 0, 40, 10)) - 10) < 1e-9

    def test_seg_box_dist_crossing_interior_is_zero(self):
        assert seg_box_dist((0, 5), (40, 5), (10, 0, 30, 10)) == 0.0

    def test_seg_box_dist_diagonal_near_corner(self):
        # Segment passes diagonally past the box's top-right corner
        # (20,10); closest approach is ~2px off the corner.
        d = seg_box_dist((15, 20), (30, 0), (0, 0, 20, 10))
        assert 1.5 < d < 2.5

    def test_seg_seg_dist_parallel(self):
        assert abs(seg_seg_dist((0, 0), (10, 0), (0, 10), (10, 10)) - 10) < 1e-9

    def test_seg_seg_dist_crossing(self):
        assert seg_seg_dist((0, 0), (10, 10), (0, 10), (10, 0)) == 0.0

    def test_seg_seg_dist_disjoint_span(self):
        # Collinear but disjoint: gap between x=5 and x=8.
        assert abs(seg_seg_dist((0, 0), (5, 0), (8, 0), (12, 0)) - 3) < 1e-9


# ---------------------------------------------------------------------------
# Strip construction
# ---------------------------------------------------------------------------

class TestStripForEdge:
    def test_strip_carries_corridor_half_width(self):
        s = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5)
        assert s.half_w == 1.5 / 2 + s.pad

    def test_strip_label_extent_included(self):
        s = strip_for_edge([(0, 0), (200, 0)], stroke_width=1.5,
                           label_text="hello")
        assert s.label is not None
        # One-sided, above the stroke: strip bottom sits at the stroke.
        assert s.label[1] <= 0 <= s.label[3]

    def test_strip_no_label(self):
        s = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5)
        assert s.label is None

    def test_forward_arrow_caps_end(self):
        s = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5, arrow="forward")
        assert s.arrow_end > 0
        assert s.arrow_start == 0

    def test_back_arrow_caps_start(self):
        s = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5, arrow="back")
        assert s.arrow_start > 0
        assert s.arrow_end == 0


# ---------------------------------------------------------------------------
# Strip vs rect
# ---------------------------------------------------------------------------

BOX = (40, -10, 60, 10)   # a 20x20 box centred on (50, 0)


class TestStripVsRect:
    def test_stroke_clearing_box_is_clear(self):
        # Horizontal stroke 10px above the box top (y=-20 vs box y0=-10).
        s = strip_for_edge([(0, -20), (100, -20)], stroke_width=1.5)
        assert not s.hits_rect(BOX)

    def test_stroke_through_box_hits(self):
        s = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5)
        assert s.hits_rect(BOX)

    def test_corridor_margin_counts_as_hit(self):
        # Stroke 2px above the box top — inside the swept corridor
        # (half stroke + pad) even though the stroke itself misses.
        s = strip_for_edge([(0, -12), (100, -12)], stroke_width=1.5)
        assert s.half_w >= 1.5 / 2
        assert s.hits_rect(BOX)

    def test_label_extent_hits_box(self):
        # Stroke clears the box by its corridor; the one-sided label
        # extent (above the stroke, toward the box) reaches into it.
        clear = strip_for_edge([(30, 20), (170, 20)], stroke_width=1.5,
                               label_text="hi")
        assert not clear.hits_rect(BOX)
        hits = strip_for_edge([(30, 20), (170, 20)], stroke_width=1.5,
                              label_text="a very long label indeed")
        assert hits.hits_rect(BOX)

    def test_arrowhead_cap_hits(self):
        # Path ends just beside the box; the arrowhead cap reaches in.
        s = strip_for_edge([(0, 0), (35, 0)], stroke_width=1.5, arrow="forward")
        assert s.arrow_end >= ARROWHEAD_SIZE / 2
        assert s.hits_rect(BOX)


# ---------------------------------------------------------------------------
# Strip vs strip
# ---------------------------------------------------------------------------

class TestStripVsStrip:
    def test_well_separated_strips_clear(self):
        a = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5)
        b = strip_for_edge([(0, 20), (100, 20)], stroke_width=1.5)
        assert not strips_overlap(a, b)

    def test_coincident_strips_overlap(self):
        a = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5)
        b = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5)
        assert strips_overlap(a, b)

    def test_corridors_within_margin_overlap(self):
        a = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5)
        b = strip_for_edge([(0, 5), (100, 5)], stroke_width=1.5)
        # 5px apart, two ~2.75px corridors: overlap.
        assert strips_overlap(a, b)

    def test_crossing_strips_overlap(self):
        a = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5)
        b = strip_for_edge([(50, -50), (50, 50)], stroke_width=1.5)
        assert strips_overlap(a, b)

    def test_label_vs_label_overlap(self):
        a = strip_for_edge([(0, 100), (200, 100)], stroke_width=1.5,
                           label_text="label one rides here")
        b = strip_for_edge([(0, 96), (200, 96)], stroke_width=1.5,
                            label_text="label two rides here")
        assert strips_overlap(a, b)

    def test_label_vs_corridor_overlap(self):
        # B's stroke passes through where A's label rides.
        a = strip_for_edge([(0, 20), (200, 20)], stroke_width=1.5,
                           label_text="label rides above")
        b = strip_for_edge([(0, 12), (200, 12)], stroke_width=1.5)
        assert strips_overlap(a, b)

    def test_anti_parallel_pair_same_geometry_overlaps(self):
        # The HA mesh defect: two anti-parallel strokes on one line.
        a = strip_for_edge([(0, 0), (100, 0)], stroke_width=1.5, arrow="forward")
        b = strip_for_edge([(100, 0), (0, 0)], stroke_width=1.5, arrow="forward")
        assert strips_overlap(a, b)


class TestLabelDirection:
    def test_vertical_labels_follow_the_arrow_direction(self):
        """The street-name paradigm (review round 1): a vertical leg's
        label reads along the arrow — a downward arrow's label reads
        top-to-bottom (unmirrored), an upward one bottom-to-top. The
        old rule mirrored every downward leg, so its label always read
        against the arrow."""
        from ggarch.geometry import label_geometry
        down = label_geometry([(100, 40), (100, 200)], "uses (one)")
        assert down.mirror is False
        assert down.uy > 0  # reads top-to-bottom, with the arrow
        up = label_geometry([(100, 200), (100, 40)], "uses (one)")
        assert up.mirror is False
        assert up.uy < 0    # reads bottom-to-top, with the arrow
