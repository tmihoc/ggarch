"""The juju preset: one grey per mode, and the entity kind."""
from ggarch.presets import JUJU_PRESET


def _light():
    return JUJU_PRESET.node_light


def _dark():
    return JUJU_PRESET.node_dark


class TestGrey:
    def test_outside_nodes_share_one_grey_per_mode(self):
        for nodes in (_light(), _dark()):
            greys = {nodes[t].stroke for t in ("person", "external", "workload")}
            assert len(greys) == 1

    def test_grey_is_visible_on_each_canvas(self):
        # Light: darker than the old #AAAAAA (2.3:1 on white).
        assert _light()["external"].stroke == "#8A8A8A"
        # Dark: lighter than the old #666666 (2.9:1 on #1E1E2E).
        assert _dark()["external"].stroke == "#A3A3AD"

    def test_dark_borders_are_heavier_and_orange_matches_grey(self):
        assert _dark()["external"].stroke_width > _light()["external"].stroke_width
        # One weight per mode: orange and grey borders read as equals.
        for nodes in (_light(), _dark()):
            assert nodes["juju-software"].stroke_width == nodes["external"].stroke_width


class TestEntityKind:
    def test_entity_is_orange_with_a_dotted_border(self):
        for nodes in (_light(), _dark()):
            style = nodes["entity"]
            assert style.stroke == nodes["juju-software"].stroke  # Juju orange
            assert style.stroke_dash == "2,2"
            assert style.badge == ""  # a plain box, no kind badge
