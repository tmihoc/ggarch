"""Renderer tests — SVG output validation."""
import re
import math
import pytest
from ggarch import parse, validate
from ggarch.solver import solve
from ggarch.router import route
from ggarch.renderer import render, render_both


def pipeline(src: str, view_name: str | None = None, dark: bool = False) -> str:
    f = parse(src)
    validate(f)
    diagram = f.diagrams[0] if not view_name else next(
        d for d in f.diagrams if d.name == view_name
    )
    model = f.get_model(diagram.model_name)
    layout = solve(diagram, model)
    rl = route(layout, model, diagram.select)
    return render(rl, model, diagram, dark=dark)


SIMPLE = """\
model "M" {
  nodes {
    a [type: juju-software, label: "Controller"]
    b [type: charm, label: "Charm"]
  }
  edges {
    a -> b [type: control, label: "exec dispatch"]
  }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 80 }
}
"""


class TestSVGStructure:
    def test_produces_svg_element(self):
        svg = pipeline(SIMPLE)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_has_node_group(self):
        svg = pipeline(SIMPLE)
        assert 'id="ggarch-nodes"' in svg

    def test_has_edge_group(self):
        svg = pipeline(SIMPLE)
        assert 'id="ggarch-edges"' in svg

    def test_has_annotation_group(self):
        svg = pipeline(SIMPLE)
        assert 'id="ggarch-annotations"' in svg

    def test_has_arrowhead_marker(self):
        svg = pipeline(SIMPLE)
        assert 'id="arrow"' in svg

    def test_has_viewbox(self):
        svg = pipeline(SIMPLE)
        assert "viewBox" in svg or "width" in svg


class TestNodeRendering:
    def test_label_text_present(self):
        svg = pipeline(SIMPLE)
        assert "Controller" in svg
        assert "Charm" in svg

    def test_juju_software_border_is_orange(self):
        svg = pipeline(SIMPLE)
        assert "#E95420" in svg

    def test_dark_mode_differs_in_text_colour(self):
        light = pipeline(SIMPLE, dark=False)
        dark  = pipeline(SIMPLE, dark=True)
        assert "#CDD6F4" in dark
        assert "#333333" in light

    def test_render_both_returns_two_strings(self):
        f = parse(SIMPLE)
        validate(f)
        diagram = f.diagrams[0]
        model = f.get_model(diagram.model_name)
        layout = solve(diagram, model)
        rl = route(layout, model, diagram.select)
        light, dark = render_both(rl, model, diagram)
        assert "<svg" in light
        assert "<svg" in dark
        assert light != dark

    def test_container_node_renders(self):
        src = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      agent [type: juju-software, label: "Agent"]
    }
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: pod }
}
"""
        svg = pipeline(src)
        assert "Pod" in svg
        assert "Agent" in svg

    def test_lifecycle_init_dashed_stroke(self):
        src = """\
model "M" {
  nodes {
    x [type: juju-software, label: "Init", lifecycle: init]
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: x }
}
"""
        svg = pipeline(src)
        # Init lifecycle should produce a dashed stroke.
        assert "stroke-dasharray" in svg or "dasharray" in svg

    def test_database_is_a_rounded_box_with_a_cylinder_badge(self):
        src = """\
model "M" {
  nodes {
    db [type: database, label: "DB"]
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: db }
}
"""
        svg = pipeline(src)
        # Every node is a rounded rectangle; the kind is a badge path.
        assert "<ellipse" not in svg
        assert 'stroke-width="1.2"' in svg

    def test_person_shape(self):
        src = """\
model "M" {
  nodes {
    u [type: person, label: "User"]
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: u }
}
"""
        svg = pipeline(src)
        assert "User" in svg
        assert "<circle" in svg


class TestEdgeRendering:
    def test_edge_path_present(self):
        svg = pipeline(SIMPLE)
        assert "<path" in svg

    def test_edge_label_present(self):
        svg = pipeline(SIMPLE)
        # Label may be wrapped across lines; check all words appear.
        assert "exec" in svg
        assert "dispatch" in svg

    def test_stream_edge_dashed(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges { a -> b [type: stream, label: "watch"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 40 }
}
"""
        svg = pipeline(src)
        assert "dasharray" in svg

    def test_forward_arrow_marker(self):
        svg = pipeline(SIMPLE)
        assert "marker-end" in svg or "marker_end" in svg


class TestAnnotationRendering:
    def test_box_annotation_renders(self):
        src = """\
model "M" {
  nodes {
    a [type: juju-software, label: "A"]
    b [type: juju-software, label: "B"]
  }
  edges { a -> b [type: api, label: "x"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 40 }
  annotations {
    box [nodes: "a b", label: "group", style: dashed, color: "#E95420"]
  }
}
"""
        svg = pipeline(src)
        assert "group" in svg
        assert "#E95420" in svg

    def _box_src(self, label_position_attr: str) -> str:
        attr = f", label-position: {label_position_attr}" if label_position_attr else ""
        return f"""\
model "M" {{
  nodes {{
    a [type: juju-software, label: "A"]
    b [type: juju-software, label: "B"]
  }}
  edges {{}}
}}
diagram "D" from "M" {{
  select {{ nodes: a b }}
  positions {{ a left-of b gap: 40 }}
  annotations {{
    box [nodes: "a b", label: "region"{attr}]
  }}
}}
"""

    def test_box_label_position_default_is_top(self):
        # Default (no label-position) renders without error and contains label.
        svg = pipeline(self._box_src(""))
        assert "region" in svg

    def test_box_label_position_top(self):
        svg = pipeline(self._box_src("top"))
        assert "region" in svg

    def test_box_label_position_bottom(self):
        svg = pipeline(self._box_src("bottom"))
        assert "region" in svg

    def test_box_label_position_left(self):
        svg = pipeline(self._box_src("left"))
        assert "region" in svg

    def test_box_label_position_right(self):
        svg = pipeline(self._box_src("right"))
        assert "region" in svg

    def test_box_label_position_bottom_differs_from_top(self):
        # The y-coordinate of the label text differs between top and bottom.
        top_svg    = pipeline(self._box_src("top"))
        bottom_svg = pipeline(self._box_src("bottom"))
        # Both render the label; the SVGs differ (different y values).
        assert "region" in top_svg
        assert "region" in bottom_svg
        assert top_svg != bottom_svg

    def test_box_label_position_left_uses_text_anchor_end(self):
        # Label sits outside the left edge, anchored rightward toward the box.
        svg = pipeline(self._box_src("left"))
        assert 'text-anchor="end"' in svg

    def test_box_label_position_right_uses_text_anchor_start(self):
        # Label sits outside the right edge, anchored leftward toward the box.
        svg = pipeline(self._box_src("right"))
        assert 'text-anchor="start"' in svg

    def test_badge_annotation_renders(self):
        src = """\
model "M" {
  nodes {
    a [type: juju-software, label: "A"]
  }
  edges {}
}
diagram "D" from "M" {
  select { nodes: a }
  annotations {
    badge [anchor: a, text: "(init)"]
  }
}
"""
        svg = pipeline(src)
        assert "(init)" in svg


class TestJujuRender:
    def test_k8s_topology_renders_light(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "topology.ggarch").read_text()
        svg = pipeline(src, "K8s deployment topology", dark=False)
        assert "<svg" in svg
        assert "Controller pod" in svg
        assert "Unit pod" in svg

    def test_k8s_topology_renders_dark(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "topology.ggarch").read_text()
        svg = pipeline(src, "K8s deployment topology", dark=True)
        assert "<svg" in svg
        assert "#1E1E2E" in svg

    def test_unit_focus_renders(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "topology.ggarch").read_text()
        svg = pipeline(src, "Unit focus", dark=False)
        assert "Unit agent" in svg
        assert "Charm" in svg


CUSTOM_EDGE = """\
model "M" {
  style {
    extends: juju
    edge cloud-call { stroke: "#8E44AD" stroke-width: 2 }
    @dark { edge cloud-call { stroke: "#BB8FCE" } }
  }
  nodes {
    a [type: juju-software, label: "Client"]
    b [type: external, label: "Cloud"]
  }
  edges {
    a -> b [type: cloud-call, label: "provision host"]
  }
}
diagram "D" from "M" {
  select { nodes: a b edges: type cloud-call }
  positions { a left-of b gap: 120 }
  annotations { legend [position: "bottom-right"] }
}
"""


class TestCustomEdgeTypes:
    """Regression: declared edge styles must reach the rendered edge.

    Before the fix, custom edge types collapsed to the literal name
    "custom" at parse time, so the style bank never matched and custom
    edges silently rendered with default styling (SPEC open question 4
    closed on a mechanism that did not exist for edges).
    """

    def test_custom_edge_type_keeps_name_end_to_end(self):
        from ggarch.router import route
        f = parse(CUSTOM_EDGE)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model("M")
        rl = route(solve(d, m), m, d.select)
        assert {e.edge_type for e in rl.edges} == {"cloud-call"}

    def test_custom_edge_style_renders_light(self):
        svg = pipeline(CUSTOM_EDGE)
        assert "#8E44AD" in svg

    def test_custom_edge_style_renders_dark(self):
        svg = pipeline(CUSTOM_EDGE, dark=True)
        assert "#BB8FCE" in svg

    def test_custom_edge_style_renders_in_legend(self):
        svg = pipeline(CUSTOM_EDGE)
        # Legend line sample for the custom type uses the declared stroke.
        assert "#8E44AD" in svg.split('id="ggarch-annotations"')[1]

    def test_edge_type_filter_is_exact_for_custom_names(self):
        from ggarch.router import route
        src = CUSTOM_EDGE.replace(
            "edges {\n    a -> b [type: cloud-call, label: \"provision host\"]\n  }",
            "edges {\n    a -> b [type: cloud-call, label: \"provision host\"]\n"
            "    a -> b [type: api, label: \"rpc\"]\n  }",
        )
        f = parse(src)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model("M")
        rl = route(solve(d, m), m, d.select)
        assert {e.edge_type for e in rl.edges} == {"cloud-call"}


GAP_BUDGET_SRC = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      a [type: charm, label: "Charm"]
      b [type: pebble, label: "Pebble"]
    }
  }
  edges {
    a -> b [type: ipc, label: "calls Pebble API"]
  }
}
diagram "D" from "M" {
  select {
    nodes: pod
    instances: pod [ { id: p1, label: "Pod 1" } ]
  }
}
"""

ALONG_PATH_SRC = """\
model "M" {
  nodes {
    a [type: juju-software, label: "A"]
    b [type: juju-software, label: "B"]
  }
  edges { a -> b [type: control, label: "one two three"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 60 }
}
"""


RTL_SRC = """\
model "M" {
  nodes {
    a [type: juju-software, label: "A"]
    b [type: juju-software, label: "B"]
  }
  edges { b -> a [type: control, label: "reverse"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 100 }
}
"""


PAIR_SRC = """\
model "M" {
  nodes {
    a [type: juju-software, label: "A"]
    b [type: juju-software, label: "B"]
  }
  edges {
    a -> b [type: control, label: "sync"]
    b -> a [type: control, label: "ack"]
  }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 120 }
}
"""


DASHED_LABELED_SRC = """\
model "M" {
  nodes {
    a [type: juju-software, label: "A"]
    b [type: juju-software, label: "B"]
  }
  edges { a -> b [type: stream, label: "watch"] }
}
diagram "D" from "M" {
  select { nodes: a b }
  positions { a left-of b gap: 100 }
}
"""


class TestAlongPathLabels:
    """ADR-002 (0.25.4): edge labels follow the arrow.

    The label rides the longest leg on an SVG textPath, above the line
    in the text's local frame, one textPath per wrapped line stacked
    outward. The stroke is never interrupted (gap/offset mode is
    abolished) and right-to-left legs get a mirrored label path so
    text always reads left-to-right or top-to-bottom.
    """

    def test_labelled_edge_renders_single_unbroken_stroke(self):
        svg = pipeline(GAP_BUDGET_SRC)
        edges = svg.split('id="ggarch-edges"')[1]
        n_paths = len(re.findall(r"<path ", edges))
        assert n_paths == 1, (
            f"labelled edge rendered {n_paths} stroke paths -- "
            "the stroke must never be split or interrupted"
        )

    def test_label_rides_textpath_with_start_offset(self):
        svg = pipeline(SIMPLE)
        assert "<textPath" in svg, "label must ride the path via textPath"
        assert "startOffset" in svg

    def test_wrap_budget_is_leg_minus_side_padding(self):
        # 60px leg minus 2x8px side padding = 44px = 8 chars:
        # "one two" / "three" (two lines). The 0.25.3 gap budget
        # (leg minus 2x16px tails) wrapped this to three lines.
        svg = pipeline(ALONG_PATH_SRC)
        assert svg.count("<textPath") == 2

    def test_lines_read_top_to_bottom_above_the_stroke(self):
        # The wrapped block reads top-to-bottom: the FIRST wrapped line
        # is the topmost (furthest above the stroke), the last line
        # nearest. 0.25.4 shipped this inverted — line 0 nearest the
        # stroke, growing outward — so every multi-line label read
        # bottom-to-top. For rotated labels the same formula gives the
        # first-read column outermost (rotate-the-block convention).
        # Round 3: stacking is per-line PATHS translated perpendicular
        # to the stroke, NOT tspan dy — renderers disagree on dy over
        # rotated textPath glyphs (Chrome slides the line along the
        # path, dropping glyphs before the path start: the half-printed
        # "bad printer" label). The outermost line's path is offset
        # FURTHER against the reading direction's normal than the
        # inner one's.
        svg = pipeline(ALONG_PATH_SRC)
        texts = [t.strip() for t in re.findall(
            r'<text[^>]*>\s*<textPath[^>]*startOffset="[\d.]+">'
            r'(?:<tspan[^>]*>)?([^<]*?)(?:</tspan>)?\s*</textPath>', svg)]
        assert texts[:2] == ["one two", "three"], texts
        # Each line carries its own defs path; the first line's path
        # sits further from the stroke by one line height (13.5px).
        paths = re.findall(
            r'<path d="M ([\d.-]+) ([\d.-]+) L ([\d.-]+) ([\d.-]+)" id="(d\d+)"',
            svg)
        assert len(paths) >= 2, paths
        ys = sorted({float(p[1]) for p in paths
                     if p[1] == p[3]})  # horizontal label paths (y equal)
        assert len(ys) >= 2
        assert abs((ys[1] - ys[0]) - 13.5) < 0.2, ys

    def test_right_to_left_leg_gets_mirrored_label_path(self):
        # The stroke runs right-to-left; the textPath must run
        # left-to-right so the label never reads upside-down.
        svg = pipeline(RTL_SRC)
        head = svg.split('<g id="ggarch-edges"')[0]
        href = re.search(r'xlink:href="#([\w-]+)"', svg)
        assert href, "no textPath reference found"
        m = re.search(
            rf'<path d="M ([\d.]+) [\d.]+ L ([\d.]+)[^"]*" id="{href.group(1)}"',
            head,
        )
        assert m, "label path not in defs"
        assert float(m.group(1)) < float(m.group(2)), (
            "label path must run left-to-right (mirrored)"
        )

    def test_antiparallel_pair_labels_ride_their_own_strokes(self):
        # ADR-003: pairs route at distinct offsets — each label anchors
        # at the midpoint of its OWN leg (the 1/3-2/3 anchor workaround
        # is redundant once strokes separate). ADR-009: the pair now
        # also BOWS — anti-parallel same-corridor strokes draw as
        # mirrored arcs, and each label path is that arc (a quadratic),
        # translated outward. The anchor contract is unchanged: the
        # label sits at the midpoint of its own path.
        svg = pipeline(PAIR_SRC)
        # The label path each textPath references, with its length.
        paths = {}
        for m in re.finditer(
                r'<path d="M ([\d.-]+) ([\d.-]+) L ([\d.-]+) ([\d.-]+)"'
                r' id="([^"]+)"', svg):
            paths[m.group(5)] = math.hypot(
                float(m.group(3)) - float(m.group(1)),
                float(m.group(4)) - float(m.group(2)))
        for m in re.finditer(
                r'<path d="M ([\d.-]+) ([\d.-]+) Q ([\d.-]+) ([\d.-]+)'
                r' ([\d.-]+) ([\d.-]+)" id="([^"]+)"', svg):
            # The label path's length along its own reading direction:
            # the chord between the path's endpoints.
            paths[m.group(7)] = math.hypot(
                float(m.group(5)) - float(m.group(1)),
                float(m.group(6)) - float(m.group(2)))
        pairs = re.findall(
            r'<textPath xlink:href="#([^"]+)"[^>]*startOffset="([\d.-]+)"',
            svg)
        assert len(pairs) == 2, pairs
        for href, off in pairs:
            leg = paths[href]
            assert float(off) == pytest.approx(leg / 2, abs=3), (href, off, leg)

    def test_antiparallel_pair_strokes_bow_apart(self):
        # ADR-009 amended (reviewer round 22): an anti-parallel pair
        # renders as TWO PARALLEL STRAIGHT strokes on the symmetric
        # pair ports (mid ± PAIR_BIAS) — the "same look", with the
        # labels riding the OUTSIDE lanes. No arcs.
        svg = pipeline(PAIR_SRC)
        edges = svg.split('id="ggarch-edges"')[1]
        lines = [m for m in re.finditer(
            r'<path[^>]*d="M ([\d.-]+) ([\d.-]+) L ([\d.-]+) ([\d.-]+)"'
            r'[^>]*>', edges)
            if "marker-end" in m.group(0)]
        assert len(lines) == 2, lines
        ys = sorted(float(m.group(2)) for m in lines)
        # Both strokes horizontal, separated by 2*PAIR_BIAS = 12px.
        assert ys[1] - ys[0] >= 10.0, ys

    def test_dashed_labelled_edge_keeps_one_dashed_path(self):
        # Dash rhythm is content: the pattern must never restart at a
        # sub-path boundary, so a labelled dashed edge is ONE path.
        svg = pipeline(DASHED_LABELED_SRC)
        edges = svg.split('id="ggarch-edges"')[1]
        assert edges.count("stroke-dasharray") == 1


class TestRoundedJoins:
    def test_routed_paths_use_round_linejoin(self):
        # ADR-003 decision 9: v1 ships polylines with
        # stroke-linejoin="round" — one attribute, zero geometry,
        # sub-pixel corners. Rounding never participates in the search.
        svg = pipeline(PAIR_SRC)
        edge_paths = re.findall(r'<path[^>]*marker-end="url\(#arrow\)"[^>]*>', svg)
        assert edge_paths
        for p in edge_paths:
            assert 'stroke-linejoin="round"' in p, p


# ---------------------------------------------------------------------------
# ADR-004 — the arrowhead channel (commitment)
# ---------------------------------------------------------------------------

ARROW_SRC = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: event, label: "notifies"]
  }
  style { extends: juju }
}
diagram "D" from "M" {
  select { nodes: a b  edges: type event }
  positions { a left-of b gap: 60 }
}
"""


class TestArrowheadChannel:
    """ADR-004: the terminal glyph is the commitment channel — filled
    (committed), open (fire-and-forget), none (headless). Direction
    (edge.arrow) is orthogonal to shape."""

    def test_event_edges_render_open_heads(self):
        """The built-in async-notification type carries the open head."""
        svg = pipeline(ARROW_SRC)
        assert 'marker-end="url(#arrow-open)"' in svg

    def test_api_edges_keep_filled_heads(self):
        svg = pipeline(ARROW_SRC.replace("event", "api"))
        assert 'marker-end="url(#arrow)"' in svg
        assert 'marker-end="url(#arrow-open)"' not in svg

    def test_arrow_both_composes_with_open_head(self):
        """Direction composes with shape: two open heads on a both-edge."""
        svg = pipeline(ARROW_SRC.replace(
            '[type: event, label: "notifies"]',
            "[type: event, arrow: both]"))
        assert 'marker-end="url(#arrow-open)"' in svg
        assert 'marker-start="url(#arrow-open-start)"' in svg

    def test_generalization_edges_render_hollow_heads(self):
        """ADR-011: the is-a type carries the hollow triangle."""
        svg = pipeline(ARROW_SRC.replace("type: event", "type: generalization")
                                .replace("edges: type event",
                                         "edges: type generalization"))
        assert 'id="arrow-hollow"' in svg
        assert 'marker-end="url(#arrow-hollow)"' in svg
        assert 'marker-end="url(#arrow-open)"' not in svg

    def test_hollow_head_composes_with_both(self):
        """Direction composes with the hollow shape like any other."""
        svg = pipeline(ARROW_SRC.replace(
            '[type: event, label: "notifies"]',
            "[type: event, arrow: both]").replace(
            "type: event", "type: generalization").replace(
            "edges: type event", "edges: type generalization"))
        assert 'marker-end="url(#arrow-hollow)"' in svg
        assert 'marker-start="url(#arrow-hollow-start)"' in svg

    def test_custom_type_composes_channels(self):
        """A custom type picks its channels in the style block."""
        src = ARROW_SRC.replace(
            "style { extends: juju }",
            "style {\n"
            "    extends: juju\n"
            '    edge notify { stroke-dash: "6,3" arrowhead: none }\n'
            "  }").replace("type: event", "type: notify").replace(
            "edges: type event", "edges: type notify")
        svg = pipeline(src)
        assert "marker-end" not in svg  # headless
        assert 'stroke-dasharray="6,3"' in svg

    def test_unknown_arrowhead_value_rejected(self):
        """The channel is a closed enum — the preattentive limit is
        enforced by construction."""
        from ggarch.errors import ValidationError
        src = ARROW_SRC.replace(
            "style { extends: juju }",
            "style {\n"
            "    extends: juju\n"
            "    edge weird { arrowhead: curly }\n"
            "  }")
        f = parse(src)
        with pytest.raises(ValidationError, match="unknown\n?arrowhead|arrowhead"):
            validate(f)

    def test_dark_mode_open_head(self):
        dark = pipeline(ARROW_SRC, dark=True)
        assert 'marker-end="url(#arrow-open)"' in dark

    def test_open_head_marker_def_drawn_unfilled(self):
        """The open head is an unfilled chevron (shape, not fill, carries
        the commitment distinction)."""
        svg = pipeline(ARROW_SRC)
        assert re.search(
            r'<marker[^>]*id="arrow-open"[^>]*>.*?fill="none"', svg,
            re.DOTALL)


# ---------------------------------------------------------------------------
# ERD edge grammar — the architect's-idiom verdict (session 45;
# supersedes the round-24 crow's-foot): data edges render BARE — no
# arrowheads, no verb labels — with 1/m end labels at BOTH box faces
# and dashed = nullable (derived from the fk field's null: marker).
# ---------------------------------------------------------------------------

ERD_SRC = """\
model "M" {
  nodes {
    parent [type: record, label: "parent", ground: "model:parent"] {
      fields {
        uuid   [label: "uuid", type: "uuid", pk: true]
      }
    }
    child  [type: record, label: "child", ground: "model:child"] {
      fields {
        uuid       [label: "uuid", type: "uuid", pk: true]
        parent_uuid [label: "parent_uuid", type: "uuid", fk: true,
                     null: true]
      }
    }
    join   [type: record, label: "join", ground: "model:join"] {
      fields {
        child_uuid  [label: "child_uuid", type: "uuid", pk: true,
                     fk: true]
        other_uuid  [label: "other_uuid", type: "uuid", pk: true,
                     fk: true]
      }
    }
    other  [type: record, label: "other", ground: "model:other"]
    one2one [type: record, label: "one2one", ground: "model:one2one"] {
      fields {
        parent_uuid [label: "parent_uuid", type: "uuid", pk: true,
                     fk: true]
      }
    }
    legacy [type: record, label: "legacy", ground: "model:legacy"]
  }
  edges {
    child.parent_uuid   -> parent.uuid  [type: data, label: "joins (0..1)"]
    join.child_uuid     -> child.uuid   [type: data, label: "sits in (one)"]
    join.other_uuid     -> other        [type: data, label: "maps to (one)"]
    one2one.parent_uuid -> parent.uuid  [type: data, label: "is the (one)"]
    legacy -> parent        [type: data, label: "hosts 0..N"]
  }
  style { extends: juju }
}
diagram "D" from "M" {
  select {
    routing: orthogonal
    nodes: parent child join other one2one legacy
    edges: type data
  }
  positions {
    parent   right-of child   gap: 90
    parent   align-middle child
    join     below child      gap: 60
    other    right-of join    gap: 60
    one2one  below parent     gap: 60
    legacy   left-of join     gap: 60
  }
}
"""


class TestErdEdgeGrammar:
    def test_data_edge_draws_no_arrowhead_and_no_verb(self):
        svg = pipeline(ERD_SRC)
        # No arrowhead on any data path (the whole SVG is data edges).
        assert "marker-end" not in svg
        assert "marker-start" not in svg
        # The verb stays in the grammar but never renders.
        assert "joins (0..1)" not in svg
        assert ">joins<" not in svg

    def test_both_end_labels_render_at_the_faces(self):
        svg = pipeline(ERD_SRC)
        # The fk (child) end of the nullable non-unique fk reads m; the
        # referenced (parent) end reads 1. Both drawn as plain texts.
        assert re.search(r'<text[^>]*>m</text>', svg)
        assert re.search(r'<text[^>]*>1</text>', svg)

    def test_nullable_fk_draws_dashed(self):
        svg = pipeline(ERD_SRC)
        # child.parent_uuid is null: true → the edge dashes (honest
        # absence); the other fk edges stay solid.
        assert 'stroke-dasharray="6,3"' in svg

    def test_unique_fk_child_end_reads_1(self):
        """A single-column PK that is also the fk reads 1 at the child
        end (one child row per referenced row — the 1:1 case)."""
        from ggarch.router import route
        from ggarch.solver import solve
        f = parse(ERD_SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        rl = route(solve(d, m), m, d.select)
        e = next(x for x in rl.edges
                 if x.source_id == "one2one")
        assert e.source_unique is True
        src_label, tgt_label = _erd_labels_for_test(e)
        assert (src_label, tgt_label) == ("1", "1")

    def test_non_unique_fk_child_end_reads_m(self):
        """A non-unique fk column reads m at the child end (many child
        rows per referenced row)."""
        from ggarch.router import route
        from ggarch.solver import solve
        f = parse(ERD_SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        rl = route(solve(d, m), m, d.select)
        e = next(x for x in rl.edges if x.source_id == "child")
        assert e.source_unique is False
        src_label, tgt_label = _erd_labels_for_test(e)
        assert (src_label, tgt_label) == ("m", "1")

    def test_composite_pk_fk_member_reads_m(self):
        """A composite-PK fk member is NOT individually unique — its
        child end reads m (the availability_zone_subnet class)."""
        from ggarch.router import route
        from ggarch.solver import solve
        f = parse(ERD_SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        rl = route(solve(d, m), m, d.select)
        e = next(x for x in rl.edges if x.source_id == "join"
                 and x.target_id == "child")
        assert e.source_unique is False
        src_label, tgt_label = _erd_labels_for_test(e)
        assert (src_label, tgt_label) == ("m", "1")

    def test_legacy_node_qualified_edge_gets_no_labels(self):
        """NO DDL witness, NO label: legacy node-qualified spine edges
        carry no multiplicity truth the engine may invent."""
        from ggarch.router import route
        from ggarch.solver import solve
        f = parse(ERD_SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        rl = route(solve(d, m), m, d.select)
        e = next(x for x in rl.edges if x.source_id == "legacy")
        src_label, tgt_label = _erd_labels_for_test(e)
        assert (src_label, tgt_label) == ("", "")

    def test_end_labels_sit_on_the_line(self):
        """The 1/m glyphs sit ON the stroke at each end (round-2 item
        3, amending the session-44 outside-the-box-face placement):
        each glyph centre lies within 2px of an edge stroke, haloed so
        the stroke does not strike through the digit — and never
        inside a box."""
        svg = pipeline(ERD_SRC)
        assert 'paint-order="stroke"' in svg
        card_texts = re.findall(
            r'<text x="([\d.]+)" y="([\d.]+)"[^>]*>([1m])</text>', svg)
        assert card_texts, "no end labels rendered"
        segs = []
        for m in re.finditer(r'<path[^>]*d="([^"]+)"', svg):
            coords = re.findall(r'[ML] ([-\d.]+) ([-\d.]+)', m.group(1))
            pts = [(float(a), float(b)) for a, b in coords]
            segs += list(zip(pts, pts[1:]))
        assert segs, "no edge strokes rendered"
        rects = [(float(m.group(1)), float(m.group(2)),
                  float(m.group(3)), float(m.group(4)))
                 for m in re.finditer(
                     r'<rect x="([\d.]+)" y="([\d.]+)" '
                     r'width="([\d.]+)" height="([\d.]+)" '
                     r'fill="none"', svg)]
        assert rects
        for cx, cy, t in card_texts:
            x, y = float(cx), float(cy)
            dist = min(_point_seg_dist(x, y, s) for s in segs)
            assert dist <= 2.0, \
                f"end label {t!r} at ({x},{y}) is {dist:.1f}px off the stroke"
            inside = any(rx < x < rx + rw and ry < y < ry + rh
                         for rx, ry, rw, rh in rects)
            assert not inside, f"end label at ({x},{y}) sits INSIDE a box"


def _point_seg_dist(px, py, seg):
    (x1, y1), (x2, y2) = seg
    dx, dy = x2 - x1, y2 - y1
    ll = dx * dx + dy * dy
    if ll == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / ll))
    return ((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2) ** 0.5


def _erd_labels_for_test(edge):
    from ggarch.renderer import _data_edge_end_labels
    return _data_edge_end_labels(edge)


class TestDeployedBadge:
    SRC = """\
model "M" {
  nodes {
    a [type: node, label: "Deployed", deployed: true]
    b [type: node, label: "Plain"]
  }
  edges { a -> b [type: api] }
  style { extends: juju }
}
diagram "D" from "M" { select { nodes: a b  edges: type api } }
"""

    def test_deployed_node_gets_a_cloud_badge_in_its_border_colour(self):
        svg = pipeline(self.SRC)
        assert svg.count('data-deployed="true"') == 1
        assert re.search(
            r'<path d="M [^"]+" fill="none" stroke="#E95420"'
            r'[^>]*data-deployed="true"', svg)

    def test_instances_inherit_the_deployed_badge(self):
        src = self.SRC.replace(
            "select { nodes: a b  edges: type api }",
            "select { nodes: a b  edges: type api\n"
            "  instances: a [ { id: a0, label: \"A0\" }, "
            "{ id: a1, label: \"A1\" } ] }")
        assert pipeline(src).count('data-deployed="true"') == 2
