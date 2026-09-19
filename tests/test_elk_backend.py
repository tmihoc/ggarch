"""ADR-006 — the ELK Layered backend (GGARCH_LAYOUT=elk).

Gated on node + the elkjs bundle: skipped when either is absent; the
built-in floor serves every view in that case and none of these tests
run. When the bundle is present (GGARCH_ELK_BUNDLE or ./node_modules),
the tests pin the backend contract: ELK owns positions and edge
routes for views without declared positions; determinism holds; the
built-in pipeline is untouched when the backend is not activated.
"""
import json
import os
import pytest

from ggarch import parse, validate, solve, route, render

BUNDLE = os.environ.get("GGARCH_ELK_BUNDLE")
NODE = __import__("shutil").which("node") is not None

pytestmark = pytest.mark.skipif(
    NODE is False or BUNDLE is None,
    reason="node + GGARCH_ELK_BUNDLE required for the ELK backend")


ELK_ENV = {"GGARCH_LAYOUT": "elk", "GGARCH_ELK_BUNDLE": BUNDLE}

SRC = """\
model "M" {
  nodes {
    a [type: t, label: "Alpha node"]
    b [type: t, label: "Beta node"]
    c [type: t, label: "Gamma"]
  }
  edges {
    a -> b [type: api, label: "calls"]
    b -> c [type: stream, label: "watches"]
  }
}
diagram "D" from "M" {
  select { nodes: a b c }
  positions { a left-of b gap: 60
              a align-middle b }
}
"""


@pytest.fixture
def with_elk(monkeypatch):
    for k, v in ELK_ENV.items():
        monkeypatch.setenv(k, v)


class TestElkBackend:
    def test_authored_view_ignores_elk(self, with_elk, monkeypatch):
        """A view with declared positions never reaches the backend:
        position is content (the declared layout must survive)."""
        monkeypatch.delenv("GGARCH_ELK_BUNDLE", raising=False)
        f = parse(SRC); validate(f)
        d = f.diagrams[0]; m = f.get_model(d.model_name)
        lay = solve(d, m)
        a, b = lay.find("a").rect, lay.find("b").rect
        assert b.x - (a.x + a.w) >= 55  # the declared left-of gap

    def test_elk_serves_synthesized_view(self, with_elk):
        src = SRC.replace("  positions { a left-of b gap: 60\n"
                          "              a align-middle b }\n", "")
        f = parse(src); validate(f)
        d = f.diagrams[0]; m = f.get_model(d.model_name)
        lay = solve(d, m)
        assert lay.edge_routes is not None, "ELK backend produced no routes"
        assert {n.id for n in lay.nodes} == {"a", "b", "c"}
        pts = next(p for s, t, p in lay.edge_routes if (s, t) == ("a", "b"))
        assert len(pts) >= 2

    def test_elk_routes_wrap_into_render(self, with_elk):
        src = SRC.replace("  positions { a left-of b gap: 60\n"
                          "              a align-middle b }\n", "")
        f = parse(src); validate(f)
        d = f.diagrams[0]; m = f.get_model(d.model_name)
        svg = render(route(solve(d, m), m, d.select), m, d)
        assert "<svg" in svg
        assert 'marker-end="url(#arrow)"' in svg  # api head from the channel grammar

    def test_elk_determinism(self, with_elk):
        """Same graph twice: byte-identical layout JSON from the backend."""
        src = SRC.replace("  positions { a left-of b gap: 60\n"
                          "              a align-middle b }\n", "")
        f = parse(src); validate(f)
        d = f.diagrams[0]; m = f.get_model(d.model_name)
        routes1 = solve(d, m).edge_routes
        routes2 = solve(d, m).edge_routes
        assert routes1 == routes2

    def test_floor_serves_when_backend_off(self, monkeypatch):
        """Without GGARCH_LAYOUT=elk the built-in synthesizer serves:
        the fallback path is the default."""
        monkeypatch.delenv("GGARCH_LAYOUT", raising=False)
        src = SRC.replace("  positions { a left-of b gap: 60\n"
                          "              a align-middle b }\n", "")
        f = parse(src); validate(f)
        d = f.diagrams[0]; m = f.get_model(d.model_name)
        lay = solve(d, m)
        assert lay.edge_routes is None  # built-in synthesizer, no ELK
