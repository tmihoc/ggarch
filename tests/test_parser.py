"""Parser and validator tests."""
import pytest
from ggarch import parse, validate
from ggarch.errors import ParseError, ValidationError
from ggarch.model import (
    Cardinality,
    EdgeType,
    GgarchFile,
    Lifecycle,
    StepKind,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_MODEL = """\
model "Sys" {
  nodes {
    a [type: software, label: "A"]
    b [type: software, label: "B"]
  }
  edges {
    a -> b [type: api, label: "calls"]
  }
}
"""


def parse_valid(src: str) -> GgarchFile:
    f = parse(src)
    validate(f)
    return f


# ---------------------------------------------------------------------------
# Parser — model
# ---------------------------------------------------------------------------

class TestParserModel:
    def test_minimal_model_parses(self):
        f = parse_valid(MINIMAL_MODEL)
        assert len(f.models) == 1
        m = f.models[0]
        assert m.name == "Sys"
        assert len(m.nodes) == 2
        assert len(m.edges) == 1

    def test_node_attributes(self):
        src = """\
model "M" {
  nodes {
    x [type: juju-software, label: "X",
       lifecycle: init, cardinality: one-per-unit]
  }
  edges {}
}
"""
        f = parse_valid(src)
        node = f.models[0].nodes[0]
        assert node.id == "x"
        assert node.type == "juju-software"
        assert node.lifecycle == Lifecycle.INIT
        assert node.cardinality == Cardinality.ONE_PER_UNIT

    def test_nested_nodes(self):
        src = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      agent [type: software, label: "Agent"]
      charm [type: charm, label: "Charm"]
    }
  }
  edges {}
}
"""
        f = parse_valid(src)
        m = f.models[0]
        pod = m.find_node("pod")
        assert pod is not None
        assert len(pod.children) == 2
        assert m.find_node("agent") is not None
        assert m.find_node("charm") is not None

    def test_edge_types(self):
        src = MINIMAL_MODEL
        f = parse_valid(src)
        edge = f.models[0].edges[0]
        assert edge.type == EdgeType.API
        assert edge.source == "a"
        assert edge.target == "b"

    def test_all_edge_types_parse(self):
        for etype in ("api", "stream", "event", "data", "control", "ipc"):
            src = f"""\
model "M" {{
  nodes {{
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }}
  edges {{
    a -> b [type: {etype}, label: "x"]
  }}
}}
"""
            f = parse_valid(src)
            assert f.models[0].edges[0].type == EdgeType(etype)

    def test_all_lifecycles_parse(self):
        for lc in ("persistent", "init", "ephemeral"):
            src = f"""\
model "M" {{
  nodes {{
    x [type: t, label: "X", lifecycle: {lc}]
  }}
  edges {{}}
}}
"""
            f = parse_valid(src)
            assert f.models[0].nodes[0].lifecycle == Lifecycle(lc)

    def test_all_cardinalities_parse(self):
        for card in ("one-per-deployment", "one-per-model",
                     "one-per-application", "one-per-unit", "one-per-host"):
            src = f"""\
model "M" {{
  nodes {{
    x [type: t, label: "X", cardinality: {card}]
  }}
  edges {{}}
}}
"""
            f = parse_valid(src)
            assert f.models[0].nodes[0].cardinality == Cardinality(card)


# ---------------------------------------------------------------------------
# Parser — behaviours
# ---------------------------------------------------------------------------

class TestParserBehaviours:
    def test_simple_behaviour(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "x"]
  }
  behaviours {
    behaviour "do thing" {
      a -> b: call "step 1"
      b -> a: return "done"
    }
  }
}
"""
        f = parse_valid(src)
        b = f.models[0].behaviours[0]
        assert b.name == "do thing"
        assert len(b.steps) == 2
        assert b.steps[0].kind == StepKind.CALL
        assert b.steps[0].source == "a"
        assert b.steps[0].target == "b"
        assert b.steps[1].kind == StepKind.RETURN

    def test_loop_block(self):
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
      loop "repeat" {
        a -> b: call "ping"
        b -> a: return "pong"
      }
    }
  }
}
"""
        f = parse_valid(src)
        step = f.models[0].behaviours[0].steps[0]
        assert step.kind == "loop"
        assert step.label == "repeat"
        assert len(step.body) == 2

    def test_alt_block(self):
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
"""
        f = parse_valid(src)
        step = f.models[0].behaviours[0].steps[0]
        assert step.kind == "alt"
        assert len(step.else_branches) == 1

    def test_self_step(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
  }
  edges {}
  behaviours {
    behaviour "self action" {
      a -> a: self "initialise"
    }
  }
}
"""
        f = parse_valid(src)
        step = f.models[0].behaviours[0].steps[0]
        assert step.kind == StepKind.SELF
        assert step.source == "a"
        assert step.target == "a"

    def test_participants(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "x"]
  }
  behaviours {
    behaviour "thing" {
      a -> b: call "go"
    }
  }
}
"""
        f = parse_valid(src)
        b = f.models[0].behaviours[0]
        assert b.all_participants() == {"a", "b"}


# ---------------------------------------------------------------------------
# Parser — diagram views
# ---------------------------------------------------------------------------

class TestParserDiagramView:
    def test_minimal_diagram(self):
        src = MINIMAL_MODEL + """\
diagram "Top" from "Sys" {
  select {
    nodes: a b
  }
}
"""
        f = parse_valid(src)
        assert len(f.diagrams) == 1
        d = f.diagrams[0]
        assert d.name == "Top"
        assert d.model_name == "Sys"
        assert d.select.node_ids == ["a", "b"]

    def test_positions_block(self):
        src = MINIMAL_MODEL + """\
diagram "Top" from "Sys" {
  select { nodes: a b }
  positions {
    a left-of b gap: 40
    a align-middle b
  }
}
"""
        f = parse_valid(src)
        constraints = f.diagrams[0].constraints
        assert len(constraints) == 2
        assert constraints[0].kind == "left-of"
        assert constraints[0].gap == 40
        assert constraints[1].kind == "align-middle"

    def test_collapse_expand(self):
        src = """\
model "M" {
  nodes {
    pod [type: container, label: "Pod"] {
      a [type: t, label: "A"]
    }
    b [type: t, label: "B"]
  }
  edges {}
}
diagram "D" from "M" {
  select {
    nodes: pod b
    collapse: pod
  }
}
"""
        f = parse_valid(src)
        assert f.diagrams[0].select.collapse == ["pod"]

    def test_annotations(self):
        src = MINIMAL_MODEL + """\
diagram "Top" from "Sys" {
  select { nodes: a b }
  annotations {
    box [nodes: "a b", label: "group", style: dashed, color: "#666"]
    callout [anchor: a, text: "note", position: above]
  }
}
"""
        f = parse_valid(src)
        anns = f.diagrams[0].annotations
        assert len(anns) == 2


# ---------------------------------------------------------------------------
# Parser — sequence views
# ---------------------------------------------------------------------------

class TestParserSequenceView:
    def test_sequence_view(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {
    a -> b [type: api, label: "x"]
  }
  behaviours {
    behaviour "thing" {
      a -> b: call "go"
    }
  }
}
sequence "Thing seq" from "M" {
  select {
    behaviour: "thing"
  }
}
"""
        f = parse_valid(src)
        assert len(f.sequences) == 1
        s = f.sequences[0]
        assert s.name == "Thing seq"
        assert s.select.behaviour == "thing"


# ---------------------------------------------------------------------------
# Validator — error cases
# ---------------------------------------------------------------------------

class TestValidatorErrors:
    def test_edge_unknown_source(self):
        src = """\
model "M" {
  nodes { b [type: t, label: "B"] }
  edges { ghost -> b [type: api, label: "x"] }
}
"""
        f = parse(src)
        with pytest.raises(ValidationError, match="ghost"):
            validate(f)

    def test_edge_unknown_target(self):
        src = """\
model "M" {
  nodes { a [type: t, label: "A"] }
  edges { a -> ghost [type: api, label: "x"] }
}
"""
        f = parse(src)
        with pytest.raises(ValidationError, match="ghost"):
            validate(f)

    def test_behaviour_unknown_participant(self):
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

    def test_behaviour_step_no_declared_edge(self):
        src = """\
model "M" {
  nodes {
    a [type: t, label: "A"]
    b [type: t, label: "B"]
  }
  edges {}
  behaviours {
    behaviour "bad" {
      a -> b: call "no edge declared"
    }
  }
}
"""
        f = parse(src)
        with pytest.raises(ValidationError, match="does not correspond to any declared edge"):
            validate(f)

    def test_view_unknown_model(self):
        src = """\
model "M" {
  nodes { a [type: t, label: "A"] }
  edges {}
}
diagram "D" from "NoSuchModel" {
  select { nodes: a }
}
"""
        f = parse(src)
        with pytest.raises(ValidationError, match="NoSuchModel"):
            validate(f)

    def test_view_unknown_node(self):
        src = MINIMAL_MODEL + """\
diagram "D" from "Sys" {
  select { nodes: a ghost }
}
"""
        f = parse(src)
        with pytest.raises(ValidationError, match="ghost"):
            validate(f)

    def test_sequence_view_unknown_behaviour(self):
        src = """\
model "M" {
  nodes { a [type: t, label: "A"] }
  edges {}
}
sequence "S" from "M" {
  select { behaviour: "no such" }
}
"""
        f = parse(src)
        with pytest.raises(ValidationError, match="no such"):
            validate(f)

    def test_self_step_allowed_without_edge(self):
        """Self-steps (src == tgt) do not require a declared edge."""
        src = """\
model "M" {
  nodes { a [type: t, label: "A"] }
  edges {}
  behaviours {
    behaviour "b" {
      a -> a: self "think"
    }
  }
}
"""
        f = parse(src)
        validate(f)  # must not raise


# ---------------------------------------------------------------------------
# Integration — real juju.ggarch example
# ---------------------------------------------------------------------------

class TestJujuExample:
    def test_juju_example_parses_and_validates(self, tmp_path):
        from pathlib import Path
        example = Path(__file__).parent.parent / "examples" / "topology.ggarch"
        src = example.read_text(encoding="utf-8")
        f = parse_valid(src)
        assert len(f.models) == 1
        m = f.models[0]
        assert m.name == "Juju"

    def test_juju_model_has_expected_nodes(self, tmp_path):
        from pathlib import Path
        example = Path(__file__).parent.parent / "examples" / "topology.ggarch"
        src = example.read_text(encoding="utf-8")
        f = parse_valid(src)
        m = f.models[0]
        node_ids = m.all_node_ids()
        for expected in ("user", "client", "controller_pod", "unit_pod",
                         "unit_agent", "charm", "workload", "pebble",
                         "dqlite", "config_seed", "charm_init"):
            assert expected in node_ids, f"expected node {expected!r} not found"

    def test_juju_model_has_no_behaviours(self, tmp_path):
        from pathlib import Path
        example = Path(__file__).parent.parent / "examples" / "topology.ggarch"
        src = example.read_text(encoding="utf-8")
        f = parse_valid(src)
        # topology.ggarch is a pure topology model — behaviours live in sequence.ggarch
        assert len(f.models[0].behaviours) == 0

    def test_juju_has_two_diagram_views(self, tmp_path):
        from pathlib import Path
        example = Path(__file__).parent.parent / "examples" / "topology.ggarch"
        src = example.read_text(encoding="utf-8")
        f = parse_valid(src)
        names = {d.name for d in f.diagrams}
        assert "K8s deployment topology" in names
        assert "Unit focus" in names

    def test_sequence_example_has_two_sequences(self, tmp_path):
        from pathlib import Path
        example = Path(__file__).parent.parent / "examples" / "sequence.ggarch"
        src = example.read_text(encoding="utf-8")
        f = parse_valid(src)
        names = {s.name for s in f.sequences}
        assert "Hook execution" in names
        assert "Bootstrap K8s" in names
