"""Sequence renderer tests."""
import pytest
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


class TestJujuSequence:
    def test_hook_execution_renders(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
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
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
        f = parse(src)
        validate(f)
        seq = next(s for s in f.sequences if s.name == "Bootstrap K8s")
        model = f.get_model(seq.model_name)
        svg = render_sequence(seq, model, dark=False)
        assert "<svg" in svg
        assert "juju bootstrap" in svg

    def test_both_modes_differ(self):
        from pathlib import Path
        src = (Path(__file__).parent.parent / "examples" / "juju.ggarch").read_text()
        f = parse(src)
        validate(f)
        seq = next(s for s in f.sequences if s.name == "Hook execution")
        model = f.get_model(seq.model_name)
        light, dark = render_sequence_both(seq, model)
        assert light != dark
        assert "#1E1E2E" in dark
