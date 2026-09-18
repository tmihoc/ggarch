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


UNITER_SRC = """\
model "M" {
  nodes {
    uop_idle       [type: juju-software, label: "idle"]
    uop_preparing  [type: juju-software, label: "preparing"]
    uop_executing  [type: juju-software, label: "executing"]
    uop_committing [type: juju-software, label: "committing"]
    uop_error      [type: juju-software, label: "error"]
  }
  edges {
    uop_idle       -> uop_preparing  [type: control]
    uop_preparing  -> uop_executing  [type: control]
    uop_executing  -> uop_committing [type: control]
    uop_executing  -> uop_error      [type: control]
    uop_error      -> uop_idle       [type: control]
    uop_committing -> uop_idle       [type: control]
  }
  behaviours {
    behaviour "Uniter operation" {
      uop_idle       -> uop_preparing:  call "resolve hook"       [on: "hook queued"]
      uop_preparing  -> uop_executing:  call "snapshot + run"
      uop_executing  -> uop_committing: return "exit 0"           [guard: "hook exits 0"]
      uop_executing  -> uop_error:     async "fail"               [guard: "hook fails"]
      uop_error      -> uop_idle:      return "retry / escalate" [on: "retry"]
      uop_committing -> uop_idle:      return "commit state"     [on: "write complete"]
    }
  }
  style { extends: juju }
}
state "Uniter" from "M" {
  select { behaviour: "Uniter operation" }
}
"""


import re as _re


def _texts(svg: str) -> list[tuple[str, float, float]]:
    """(label, x, y) for every centred text in the SVG."""
    out = []
    for m in _re.finditer(r'<text([^>]*)>(.*?)</text>', svg):
        a, t = m.group(1), m.group(2)
        if 'text-anchor="middle"' not in a:
            continue
        out.append((t,
                    float(_re.search(r'x="([-\d.]+)"', a).group(1)),
                    float(_re.search(r'y="([-\d.]+)"', a).group(1))))
    return out


class TestLayeredLayout:
    """Layered state layout (0.25.0).

    Before: states wrapped into rows of 4 in appearance order, so a branch
    target (error) landed in a second row under column 0 and its incoming
    edge crossed the forward labels -- the measured collision in the juju
    uniter machine ("[hook fails] / fail" overlapping "/ snapshot + run").
    Now: columns follow topological depth, branch targets stack below
    their entry column, and back edges bow outside the machine.
    """

    def _uniter_svg(self):
        f = parse(UNITER_SRC); validate(f)
        sv = f.states[0]; m = f.get_model(sv.model_name)
        return render_state(sv, m)

    def test_branch_state_stacks_below_entry_column(self):
        svg = self._uniter_svg()
        pos = {t: (x, y) for t, x, y in _texts(svg)}
        # error shares committing's column (its entry state's column),
        # stacked below the chain row -- not wrapped to the far left.
        assert abs(pos["error"][0] - pos["committing"][0]) < 1.0
        assert pos["error"][1] > pos["committing"][1]

    def test_no_transition_label_collisions(self):
        # The shipped defect: two transition labels overlapping. Every
        # pair of rendered texts must be disjoint (state names excluded --
        # they sit inside their own boxes by design).
        svg = self._uniter_svg()
        bb = []
        for t, x, y in _texts(svg):
            if len(t) <= 8:  # state names
                continue
            w = len(t) * 6.2
            bb.append((x - w / 2, y - 5, x + w / 2, y + 5, t))
        for i in range(len(bb)):
            for j in range(i + 1, len(bb)):
                a, b = bb[i], bb[j]
                assert (a[2] < b[0] + 1 or b[2] < a[0] + 1
                        or a[3] < b[1] + 1 or b[3] < a[1] + 1), \
                    f"labels overlap: {a[4]!r} <-> {b[4]!r}"

    def test_transition_labels_ride_the_path(self):
        # ADR-003 decision 10: transition labels adopt along-path
        # textPath (ADR-002) — one label mechanism across all three view
        # kinds. The opaque background masks die: a label riding its
        # own stroke needs no mask.
        svg = self._uniter_svg()
        # Labels ride their strokes (textPath); free-floating label
        # texts (x/y-anchored, outside state boxes) are gone.
        assert svg.count("<textPath") > 0
        assert not _re.findall(r'<rect[^>]*stroke="none"[^>]*/>', svg)

    def test_state_boxes_use_the_shared_border_radius(self):
        # One visual identity: state boxes adopt the style's
        # border_radius (juju-software = 6), not a hardcoded 8.
        svg = self._uniter_svg()
        # juju-software carries border_radius 4 in the preset — the
        # bespoke hardcoded 8 is gone.
        rxs = set(_re.findall(r'<rect[^>]*rx="(\d+)', svg))
        assert rxs == {"4"}, rxs
