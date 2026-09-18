"""Sequence renderer tests."""
import pytest
import re
from ggarch import parse, validate
from ggarch.sequence_renderer import (
    render_sequence,
    render_sequence_both,
    _ordered_participants,
    _count_rows,
)


def pipeline(src: str, view_name: str | None = None, dark: bool = False) -> str:
    f = parse(src)
    validate(f)
    seq = f.sequences[0] if not view_name else next(
        s for s in f.sequences if s.name == view_name
    )
    model = f.get_model(seq.model_name)
    return render_sequence(seq, model, dark=dark)


SIMPLE_SEQ = """\
model "M" {
  nodes {
    a [type: juju-software, label: "Client"]
    b [type: juju-software, label: "Controller"]
  }
  edges {
    a -> b [type: api, label: "deploy"]
    b -> a [type: api, label: "ok"]
  }
  behaviours {
    behaviour "deploy" {
      a -> b: call "deploy application"
      b -> a: return "done"
    }
  }
}
sequence "Deploy" from "M" {
  select { behaviour: "deploy" }
}
"""


class TestSequenceStructure:
    def test_produces_svg(self):
        svg = pipeline(SIMPLE_SEQ)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_has_lifelines(self):
        svg = pipeline(SIMPLE_SEQ)
        assert "Client" in svg
        assert "Controller" in svg

    def test_has_step_labels(self):
        svg = pipeline(SIMPLE_SEQ)
        assert "deploy application" in svg
        assert "done" in svg

    def test_dark_mode(self):
        light = pipeline(SIMPLE_SEQ, dark=False)
        dark  = pipeline(SIMPLE_SEQ, dark=True)
        assert "#1E1E2E" in dark
        assert "#FFFFFF" in light
        assert light != dark

    def test_render_both(self):
        f = parse(SIMPLE_SEQ)
        validate(f)
        seq = f.sequences[0]
        model = f.get_model(seq.model_name)
        light, dark = render_sequence_both(seq, model)
        assert "<svg" in light
        assert "<svg" in dark

    def test_dashed_line_for_return(self):
        """Return steps should produce a dashed arrow."""
        svg = pipeline(SIMPLE_SEQ)
        assert "stroke-dasharray" in svg

    def test_arrowhead_markers_defined(self):
        svg = pipeline(SIMPLE_SEQ)
        assert "seq-arrow" in svg


class TestParticipantOrdering:
    def test_order_of_first_appearance(self):
        f = parse(SIMPLE_SEQ)
        validate(f)
        model = f.models[0]
        b = model.find_behaviour("deploy")
        result = _ordered_participants(b, [], model)
        assert result == ["a", "b"]

    def test_filter_reduces_participants(self):
        f = parse(SIMPLE_SEQ)
        validate(f)
        model = f.models[0]
        b = model.find_behaviour("deploy")
        result = _ordered_participants(b, ["a"], model)
        assert result == ["a"]


class TestRowCounting:
    def test_simple_steps(self):
        f = parse(SIMPLE_SEQ)
        validate(f)
        model = f.models[0]
        b = model.find_behaviour("deploy")
        assert _count_rows(b.steps) == 2

    def test_loop_counts_inner_rows(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "x"]
    b -> a [type: api, label: "y"]
  }
  behaviours {
    behaviour "loop" {
      loop "repeat" {
        a -> b: call "ping"
        b -> a: return "pong"
      }
    }
  }
}
sequence "S" from "M" {
  select { behaviour: "loop" }
}
"""
        f = parse(src)
        validate(f)
        model = f.models[0]
        b = model.find_behaviour("loop")
        # 2 inner rows inside the loop block.
        assert _count_rows(b.steps) == 2


class TestLoopBlock:
    def test_loop_renders(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "x"]
    b -> a [type: api, label: "y"]
  }
  behaviours {
    behaviour "looping" {
      loop "during hook" {
        a -> b: call "ping"
        b -> a: return "pong"
      }
    }
  }
}
sequence "S" from "M" {
  select { behaviour: "looping" }
}
"""
        svg = pipeline(src)
        assert "during hook" in svg
        assert "ping" in svg

    def test_alt_block_renders(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "x"]
    b -> a [type: api, label: "y"]
  }
  behaviours {
    behaviour "conditional" {
      alt "success" {
        a -> b: call "ok"
      } else "failure" {
        b -> a: return "err"
      }
    }
  }
}
sequence "S" from "M" {
  select { behaviour: "conditional" }
}
"""
        svg = pipeline(src)
        assert "success" in svg
        assert "failure" in svg


class TestSelfCall:
    def test_self_call_renders(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
  }
  edges {}
  behaviours {
    behaviour "self" {
      a -> a: self "initialise"
    }
  }
}
sequence "S" from "M" {
  select { behaviour: "self" }
}
"""
        svg = pipeline(src)
        assert "initialise" in svg
        assert "<svg" in svg


PAR_SRC = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
    c [type: t, label: "C"]
  }
  edges {
    a -> b [type: api, label: "x"]
    a -> c [type: api, label: "y"]
  }
  behaviours {
    behaviour "parallel" {
      par {
        a -> b: call "notify B"
        a -> c: call "notify C"
      }
    }
  }
}
sequence "S" from "M" {
  select { behaviour: "parallel" }
}
"""

OPT_SRC = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "x"]
  }
  behaviours {
    behaviour "optional" {
      opt "if condition" {
        a -> b: call "maybe"
      }
    }
  }
}
sequence "S" from "M" {
  select { behaviour: "optional" }
}
"""

ACTIVATION_SRC = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "x"]
    b -> a [type: api, label: "y"]
  }
  behaviours {
    behaviour "req" {
      a -> b: call "request"
      b -> a: return "response"
    }
  }
}
sequence "S" from "M" {
  select { behaviour: "req" }
}
"""


class TestParBlock:
    def test_par_renders(self):
        svg = pipeline(PAR_SRC)
        assert "<svg" in svg
        assert "notify B" in svg
        assert "notify C" in svg

    def test_par_label_present(self):
        svg = pipeline(PAR_SRC)
        assert "[par]" in svg

    def test_par_uses_distinct_color(self):
        # par uses green tint, not the blue used by loop/alt
        svg = pipeline(PAR_SRC)
        assert "#66AA66" in svg  # par_stroke light mode

    def test_par_row_count(self):
        from ggarch.model import Block
        f = __import__("ggarch").parse(PAR_SRC)
        __import__("ggarch").validate(f)
        b = f.models[0].find_behaviour("parallel")
        # 2 steps in one branch — no separator rows since only one branch
        assert _count_rows(b.steps) == 2


class TestOptBlock:
    def test_opt_renders(self):
        svg = pipeline(OPT_SRC)
        assert "<svg" in svg
        assert "maybe" in svg

    def test_opt_label_present(self):
        svg = pipeline(OPT_SRC)
        assert "[opt]" in svg
        assert "if condition" in svg

    def test_opt_has_shaded_region(self):
        svg = pipeline(OPT_SRC)
        # opt uses the same block fill as loop/alt
        assert "fill-opacity" in svg


class TestActivationBars:
    def test_activation_bar_rendered_on_call_return(self):
        svg = pipeline(ACTIVATION_SRC)
        assert "<svg" in svg
        # Activation bar is a filled rectangle; distinct fill from block regions
        assert "#CCCCEE" in svg  # light mode bar fill

    def test_no_activation_bar_without_return(self):
        # A call with no matching return should not draw a bar (stack not closed)
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges { a -> b [type: api, label: "x"] }
  behaviours {
    behaviour "async" {
      a -> b: async "fire and forget"
    }
  }
}
sequence "S" from "M" { select { behaviour: "async" } }
"""
        svg = pipeline(src)
        # No activation bar fill colour should appear
        assert "#CCCCEE" not in svg

    def test_activation_bar_dark_mode(self):
        svg = pipeline(ACTIVATION_SRC, dark=True)
        assert "#334466" in svg  # dark mode bar fill


class TestJujuSequence:
    def test_hook_execution_renders(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "sequence.ggarch").read_text()
        f = parse(src)
        validate(f)
        seq = next(s for s in f.sequences if s.name == "Hook execution")
        model = f.get_model(seq.model_name)
        svg = render_sequence(seq, model, dark=False)
        assert "<svg" in svg
        assert "exec dispatch" in svg
        assert "flush writes" in svg

    def test_bootstrap_k8s_renders(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "sequence.ggarch").read_text()
        f = parse(src)
        validate(f)
        seq = next(s for s in f.sequences if s.name == "Bootstrap K8s")
        model = f.get_model(seq.model_name)
        svg = render_sequence(seq, model, dark=False)
        assert "<svg" in svg
        assert "juju bootstrap" in svg

    def test_both_modes_differ(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "sequence.ggarch").read_text()
        f = parse(src)
        validate(f)
        seq = next(s for s in f.sequences if s.name == "Hook execution")
        model = f.get_model(seq.model_name)
        light, dark = render_sequence_both(seq, model)
        assert light != dark
        assert "#1E1E2E" in dark


SELF_SEQ = """\
model "M" {
  nodes {
    a [type: juju-software, label: "Client"]
    b [type: juju-software, label: "Controller"]
  }
  edges { a -> b [type: api, label: "deploy"] }
  behaviours {
    behaviour "deploy" {
      a -> a: self "validate credentials"
      a -> b: call "deploy application"
    }
  }
}
sequence "Deploy" from "M" {
  select { behaviour: "deploy" }
}
"""


class TestSelfCallLabels:
    """Self-call labels sit beside the loop, not straddling the lifeline.

    Before 0.25.0 the label was centred on the lifeline (text-anchor
    middle, above the row): a long label -- "Write application + unit
    records" -- spanned half of each neighbouring column and struck the
    activation bars. Now it follows the UML convention: start-anchored
    to the right of the loop, vertically centred on it, with an opaque
    background masking any neighbouring-lifeline strike.
    """

    def _svg(self):
        f = parse(SELF_SEQ); validate(f)
        sv = f.sequences[0]
        return render_sequence(sv, f.get_model(sv.model_name), dark=False)

    def test_self_label_anchored_right_of_loop(self):
        svg = self._svg()
        m2 = re.search(r'<text([^>]*)>validate credentials</text>', svg)
        assert m2, "self-call label not rendered"
        attrs = m2.group(1)
        assert 'text-anchor="start"' in attrs
        x = float(re.search(r'x="([\d.]+)"', attrs).group(1))
        # The Client lifeline sits at column 0: cx = MARGIN_SIDE + 60 = 90.
        assert x > 100.0, f"label at {x} not right of the loop"

    def test_self_label_has_background_mask(self):
        svg = self._svg()
        assert 'stroke="none"' in svg


class TestFooterClearance:
    """The closing actor boxes must not cover the bottom-most arrow.

    Regression: the footer y was derived from a height budget that
    ignored the lead-in below the headers (y_start began at
    header_h + STEP_HEIGHT * 1.5, but lifeline_h only budgeted
    header_h + rows * STEP_HEIGHT). The last arrow row landed 18px
    below the footer tops and was painted over by them. The lifeline
    bottom and footer boxes are now placed from the y actually returned
    by rendering the steps.
    """

    def _geometry(self, svg, n_participants):
        height = float(re.search(r'height="(\d+)"', svg).group(1))
        paths = re.findall(r"<path[^>]*>", svg)
        arrow_ys = [
            float(re.search(r"M[0-9.]+,([0-9.]+)", p).group(1))
            for p in paths if "url(#seq-arrow" in p
        ]
        rects = re.findall(r"<rect[^>]*>", svg)
        footer_tops = [float(re.search(r' y="([0-9.]+)"', r).group(1))
                       for r in rects[-n_participants:]]
        return height, arrow_ys, footer_tops

    def test_footer_below_last_arrow(self):
        svg = pipeline(SIMPLE_SEQ)
        height, arrow_ys, footer_tops = self._geometry(svg, 2)
        assert arrow_ys, "no arrows rendered"
        assert min(footer_tops) > max(arrow_ys), (
            f"footer top {min(footer_tops)} covers last arrow {max(arrow_ys)}"
        )
        assert min(footer_tops) + 40 <= height, "footer exceeds canvas"

    def test_footer_below_trailing_block(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "x"]
    b -> a [type: api, label: "y"]
  }
  behaviours {
    behaviour "retrying" {
      a -> b: call "first"
      loop "retry" {
        a -> b: call "second"
      }
    }
  }
}
sequence "S" from "M" {
  select { behaviour: "retrying" }
}
"""
        svg = pipeline(src)
        height, arrow_ys, footer_tops = self._geometry(svg, 2)
        assert arrow_ys, "no arrows rendered"
        # The block region extends BLOCK_PAD past its last step; the
        # footer must sit below that, not just below the arrow row.
        assert min(footer_tops) > max(arrow_ys), (
            f"footer top {min(footer_tops)} covers block's last arrow {max(arrow_ys)}"
        )
        assert min(footer_tops) + 40 <= height, "footer exceeds canvas"

# ---------------------------------------------------------------------------
# Sequence polish (0.25.6)
# ---------------------------------------------------------------------------


class TestSequenceLabelProximity:
    """Message labels sit 7px above their own arrow, centred on its span.

    0.25.6 bottom-anchored the block (the nearest wrapped line sits
    7px clear of the stroke, first line topmost -- the 0.25.5 reading
    order) but also anchored it at the arrow's start, per review
    note 1's "consider". User follow-up: centred looked better -- the
    block hugged the sender and left dead space at the receiver.
    0.25.7 keeps the proximity and reverts the horizontal anchor to
    the span midpoint.
    """

    def _arrow_rows(self, svg):
        """Straight two-point arrow paths as (x_source, y, x_target)."""
        return [
            (float(m.group(1)), float(m.group(2)), float(m.group(3)))
            for m in re.finditer(
                r'<path d="M([\d.]+),([\d.]+) L([\d.]+),\2"[^>]*marker-end',
                svg,
            )
        ]

    def _label(self, svg, text):
        m = re.search(rf'<text([^>]*)>{re.escape(text)}</text>', svg)
        assert m, f"label {text!r} not rendered"
        attrs = m.group(1)
        return (
            float(re.search(r'x="([\d.]+)"', attrs).group(1)),
            float(re.search(r'y="([\d.]+)"', attrs).group(1)),
            attrs,
        )

    def test_single_line_label_seven_px_above_arrow(self):
        svg = pipeline(SIMPLE_SEQ)
        _, y, _ = self._arrow_rows(svg)[0]
        _, ly, _ = self._label(svg, "deploy application")
        assert ly == pytest.approx(y - 7), (
            f"label at {ly}, arrow at {y} -- not 7px above"
        )

    def test_label_centered_on_arrow_span(self):
        svg = pipeline(SIMPLE_SEQ)
        rows = self._arrow_rows(svg)
        # Both directions centre on their own span's midpoint.
        lx, _, attrs = self._label(svg, "deploy application")
        assert lx == pytest.approx((rows[0][0] + rows[0][2]) / 2)
        assert 'text-anchor="middle"' in attrs
        lx, _, attrs = self._label(svg, "done")
        assert lx == pytest.approx((rows[1][0] + rows[1][2]) / 2)
        assert 'text-anchor="middle"' in attrs

    def test_multiline_block_bottom_anchored_first_line_topmost(self):
        src = """\
model "M" {
  nodes {
    a [type: juju-software, label: "Client"]
    b [type: juju-software, label: "Controller"]
  }
  edges {
    a -> b [type: api, label: "deploy"]
    b -> a [type: api, label: "ok"]
  }
  behaviours {
    behaviour "deploy" {
      a -> b: call "first line\\nsecond line"
      b -> a: return "done"
    }
  }
}
sequence "Deploy" from "M" {
  select { behaviour: "deploy" }
}
"""
        svg = pipeline(src)
        _, ly0, _ = self._label(svg, "first line")
        _, y, _ = self._arrow_rows(svg)[0]
        _, ly1, _ = self._label(svg, "second line")
        assert ly0 == pytest.approx(y - 7 - 13), "first line not topmost"
        assert ly1 == pytest.approx(y - 7), "nearest line not 7px clear"


WRAP_SRC = """\
model "M" {
  nodes {
    b [type: juju-software, label: "Controller"]
    c [type: juju-software, label: "Unit agent"]
  }
  edges {
    b -> c [type: api, label: "notify"]
  }
  behaviours {
    behaviour "notify" {
      b -> c: async "watcher fires (data changed)"
    }
  }
}
sequence "Notify" from "M" {
  select { behaviour: "notify" }
}
"""


class TestSequenceWrapBudget:
    """The wrap budget is the arrow span minus fixed padding, not 85% of it.

    Regression (juju4 "Integrate"): "watcher fires (data changed)" is
    28 chars and the adjacent-column span is 180px, but
    int(180 * 0.85 / 5.5) = 27 wrapped it by one char even though it
    fits. The budget is now span - 2*LABEL_PAD (12px per side): wide
    enough to keep that label on one line, tight enough that the
    widest one-line label stays clear of the activation bars and
    lifelines the arrow connects (the arrow runs centre-to-centre;
    the bars occupy +/-5px around each centre).
    """

    def test_label_that_fits_the_span_does_not_wrap(self):
        svg = pipeline(WRAP_SRC)
        assert re.search(
            r'>watcher fires \(data changed\)</text>', svg
        ), "label wrapped although it fits the arrow span"

    def test_widest_one_line_label_stays_clear_of_the_endpoints(self):
        # 28 chars fit an adjacent-column span at 5.5px/char
        # (154px <= 180 - 24); 29 do not -- the block never runs the
        # full arrow width into the things the arrow connects.
        svg = pipeline(WRAP_SRC)
        assert re.search(
            r'>watcher fires \(data changed\)</text>', svg
        )
        longer = pipeline(WRAP_SRC.replace(
            "watcher fires (data changed)",
            "watcher fires (data changed)!",
        ))
        assert not re.search(
            r'>watcher fires \(data changed\)!</text>', longer
        ), "29-char label rendered on one line -- spans the full width"
        assert "watcher fires (data" in longer
        assert "changed)!" in longer


PERSON_SEQ_SRC = """\
model "M" {
  nodes {
    u [type: person, label: "User"]
    k [type: juju-software, label: "Controller"]
  }
  edges {
    u -> k [type: api, label: "juju deploy"]
  }
  behaviours {
    behaviour "deploy" {
      u -> k: call "juju deploy"
      k -> u: return "deployed"
    }
  }
}
sequence "Deploy" from "M" {
  select { behaviour: "deploy" }
}
"""

DB_SEQ_SRC = PERSON_SEQ_SRC.replace(
    'u [type: person, label: "User"]',
    'd [type: database, label: "Model DB"]',
).replace("u -> k", "d -> k").replace("k -> u", "k -> d").replace(
    "u: call", "d: call",
)

INIT_SEQ_SRC = PERSON_SEQ_SRC.replace(
    'k [type: juju-software, label: "Controller"]',
    'k [type: juju-software, label: "Controller", lifecycle: init]',
)


class TestTypeFaithfulParticipantHeaders:
    """One node, one visual identity across all view kinds (SPEC):
    participant headers and footers render the node's TYPE SHAPE, not
    just its colours -- a person-typed participant carries the same
    person glyph as its topology box, a database the same cylinder
    caps, and lifecycle/border styling comes from the resolved node
    style (the sequence-specific "4,3" init dash was a divergence).
    """

    def test_person_participant_carries_glyph_in_header_and_footer(self):
        svg = pipeline(PERSON_SEQ_SRC)
        # One head circle per participant box: header + footer.
        assert svg.count("<circle") == 2

    def test_database_participant_carries_cylinder_caps(self):
        svg = pipeline(DB_SEQ_SRC)
        # Two caps per participant box: header + footer.
        assert svg.count("<ellipse") == 4

    def test_init_lifecycle_dash_matches_topology(self):
        svg = pipeline(INIT_SEQ_SRC)
        assert 'stroke-dasharray="6,3"' in svg
