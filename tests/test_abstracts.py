"""Tests for the abstracts: relationship between nodes."""
import pytest
from ggarch import parse, validate
from ggarch.errors import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pv(src):
    f = parse(src)
    validate(f)
    return f


# ---------------------------------------------------------------------------
# Model-level tests
# ---------------------------------------------------------------------------

class TestAbstractsModel:

    def test_parses_abstracts_attr(self):
        src = """\
model "M" {
  nodes {
    abstract_ctrl [type: juju-software, label: "Controller"]
    controller_pod [type: container, label: "Controller pod",
                    abstracts: "abstract_ctrl"] {
      jujud [type: juju-software, label: "jujud"]
    }
  }
  edges {
    abstract_ctrl -> abstract_ctrl [type: api, label: "self"]
  }
}
"""
        f = pv(src)
        m = f.models[0]
        pod = m.find_node("controller_pod")
        assert pod.abstracts == ["abstract_ctrl"]

    def test_abstractions_map(self):
        src = """\
model "M" {
  nodes {
    ctrl [type: juju-software, label: "Controller"]
    pod  [type: container, label: "Pod", abstracts: "ctrl"]
  }
  edges { ctrl -> ctrl [type: api, label: "x"] }
}
"""
        f = pv(src)
        m = f.models[0]
        assert m.abstractions_map() == {"ctrl": "pod"}

    def test_all_valid_ids_includes_abstract(self):
        src = """\
model "M" {
  nodes {
    ctrl [type: juju-software, label: "Controller"]
    pod  [type: container, label: "Pod", abstracts: "ctrl"]
  }
  edges { ctrl -> ctrl [type: api, label: "x"] }
}
"""
        f = pv(src)
        m = f.models[0]
        assert "ctrl" in m.all_valid_ids()
        assert "pod"  in m.all_valid_ids()

    def test_abstracts_multiple(self):
        """A node can abstract multiple ids."""
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
    c [type: container, label: "C", abstracts: "a b"]
  }
  edges {
    a -> b [type: api, label: "x"]
    b -> a [type: api, label: "y"]
  }
}
"""
        f = pv(src)
        m = f.models[0]
        node_c = m.find_node("c")
        assert set(node_c.abstracts) == {"a", "b"}
        amap = m.abstractions_map()
        assert amap["a"] == "c"
        assert amap["b"] == "c"

    def test_resolve_id(self):
        src = """\
model "M" {
  nodes {
    ctrl [type: t, label: "ctrl"]
    pod  [type: container, label: "pod", abstracts: "ctrl"]
  }
  edges { ctrl -> ctrl [type: api, label: "x"] }
}
"""
        f = pv(src)
        m = f.models[0]
        assert m.resolve_id("ctrl") == "pod"
        assert m.resolve_id("pod")  == "pod"   # already concrete
        assert m.resolve_id("unknown") == "unknown"  # no mapping


# ---------------------------------------------------------------------------
# Validation — abstract ids are valid in edges and behaviours
# ---------------------------------------------------------------------------

class TestAbstractsValidation:

    def test_edge_using_abstract_id_is_valid(self):
        """An edge whose endpoint is an abstract id (covered by abstracts:) is valid."""
        src = """\
model "M" {
  nodes {
    ctrl [type: t, label: "Controller"]
    client [type: t, label: "Client"]
    pod [type: container, label: "Pod", abstracts: "ctrl"]
  }
  edges {
    client -> ctrl [type: api, label: "calls"]
  }
}
"""
        f = parse(src)
        validate(f)  # must not raise

    def test_behaviour_using_abstract_id_is_valid(self):
        """A behaviour step using an abstract id (covered by abstracts:) is valid."""
        src = """\
model "M" {
  nodes {
    ctrl   [type: t, label: "Controller"]
    client [type: t, label: "Client"]
    pod    [type: container, label: "Pod", abstracts: "ctrl"]
  }
  edges {
    client -> ctrl [type: api, label: "calls"]
    ctrl -> client [type: api, label: "returns"]
  }
  behaviours {
    behaviour "deploy" {
      client -> ctrl:   call "deploy"
      ctrl   -> client: return "done"
    }
  }
}
"""
        f = parse(src)
        validate(f)  # must not raise

    def test_undeclared_abstract_id_still_fails(self):
        """An id that is neither declared nor covered by abstracts: is still invalid."""
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
  }
  edges {
    a -> ghost [type: api, label: "x"]
  }
}
"""
        f = parse(src)
        with pytest.raises(ValidationError, match="ghost"):
            validate(f)

    def test_behaviour_abstract_participant_not_in_valid_ids_fails(self):
        """A behaviour participant not in all_valid_ids still fails."""
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges { a -> b [type: api, label: "x"] }
  behaviours {
    behaviour "bad" {
      a -> ghost: call "oops"
    }
  }
}
"""
        f = parse(src)
        with pytest.raises(ValidationError, match="ghost"):
            validate(f)


# ---------------------------------------------------------------------------
# Integration — juju.ggarch has abstracts declared
# ---------------------------------------------------------------------------

class TestJujuAbstracts:

    def test_juju_ggarch_has_abstracts(self):
        from pathlib import Path
        docs = Path(__file__).parent.parent.parent / "juju" / "docs" / "juju.ggarch"
        if not docs.exists():
            pytest.skip("docs/juju.ggarch not accessible")
        f = parse(docs.read_text())
        validate(f)
        m = f.models[0]
        amap = m.abstractions_map()
        # controller_pod should abstract controller
        assert "controller" in amap
        assert amap["controller"] == "controller_pod"

    def test_controller_abstract_id_is_valid(self):
        from pathlib import Path
        docs = Path(__file__).parent.parent.parent / "juju" / "docs" / "juju.ggarch"
        if not docs.exists():
            pytest.skip("docs/juju.ggarch not accessible")
        f = parse(docs.read_text())
        validate(f)
        m = f.models[0]
        assert "controller" in m.all_valid_ids()
