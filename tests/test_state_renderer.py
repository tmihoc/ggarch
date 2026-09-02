"""Tests for Phase 11: state view renderer."""
import pytest
from ggarch import parse, validate
from ggarch.state_renderer import render_state, render_state_both


STATE_SRC = """\
model "M" {
  nodes {
    idle    [type: juju-software, label: "Idle"]
    running [type: juju-software, label: "Running"]
    error   [type: juju-software, label: "Error"]
  }
  edges {
    idle    -> running [type: control]
    running -> idle    [type: control]
    running -> error   [type: control]
  }
  behaviours {
    behaviour "lifecycle" {
      idle    -> running: call "start"
      running -> running: self "execute"
      running -> idle:    return "stop" [guard: "clean", on: "stopped"]
      running -> error:   async  "fail"  [guard: "dirty"]
    }
  }
  style { extends: juju }
}
state "Lifecycle" from "M" {
  select { behaviour: "lifecycle" }
}
"""


def _svg(dark=False):
    f = parse(STATE_SRC); validate(f)
    sv = f.states[0]; m = f.get_model(sv.model_name)
    return render_state(sv, m, dark=dark)


class TestStateParsing:
    def test_state_view_parsed(self):
        f = parse(STATE_SRC); validate(f)
        assert len(f.states) == 1
        assert f.states[0].name == "Lifecycle"

    def test_guard_on_step(self):
        f = parse(STATE_SRC)
        b = f.models[0].find_behaviour("lifecycle")
        # Find the stop step
        stop_step = next(s for s in b.steps
                         if hasattr(s, "label") and s.label == "stop")
        assert stop_step.guard == "clean"
        assert stop_step.trigger == "stopped"

    def test_guard_dirty_step(self):
        f = parse(STATE_SRC)
        b = f.models[0].find_behaviour("lifecycle")
        fail_step = next(s for s in b.steps
                         if hasattr(s, "label") and s.label == "fail")
        assert fail_step.guard == "dirty"

    def test_validates_cleanly(self):
        f = parse(STATE_SRC); validate(f)


class TestStateRendering:
    def test_produces_svg(self):
        svg = _svg()
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_state_labels_present(self):
        svg = _svg()
        assert "Idle" in svg
        assert "Running" in svg
        assert "Error" in svg

    def test_transition_labels_present(self):
        svg = _svg()
        assert "start" in svg

    def test_guard_in_label(self):
        svg = _svg()
        # "stopped [clean] / stop" or similar
        assert "clean" in svg

    def test_initial_pseudostate_present(self):
        # Initial state circle is a filled circle
        svg = _svg()
        assert "<circle" in svg

    def test_dark_mode(self):
        light = _svg(dark=False)
        dark  = _svg(dark=True)
        assert "<svg" in dark
        assert light != dark

    def test_render_both(self):
        f = parse(STATE_SRC); validate(f)
        sv = f.states[0]; m = f.get_model(sv.model_name)
        light, dark = render_state_both(sv, m)
        assert "<svg" in light
        assert "<svg" in dark
        assert light != dark
