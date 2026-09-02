"""Tests for Phase 12: deployment environments."""
import pytest
from ggarch import parse, validate, solve, route, render
from ggarch.errors import ValidationError


ENV_SRC = """\
model "Juju" {
  nodes {
    controller   [type: juju-software, label: "Controller"]
    controller_k8s [type: container,   label: "Controller pod",
                    abstracts: "controller"]
    controller_vm  [type: container,   label: "Controller VM",
                    abstracts: "controller"]
    unit_agent   [type: juju-software, label: "Unit agent"]
  }
  edges {
    controller   -> unit_agent [type: stream]
  }
  environment kubernetes {
    present: controller_k8s unit_agent
    abstracts {
      controller: controller_k8s
    }
  }
  environment machine {
    present: controller_vm unit_agent
    abstracts {
      controller: controller_vm
    }
  }
  style { extends: juju }
}
diagram "K8s view" from "Juju" {
  select {
    nodes: controller unit_agent
    environment: kubernetes
  }
  positions {
    controller left-of unit_agent gap: 60
    controller align-middle unit_agent
  }
}
diagram "Machine view" from "Juju" {
  select {
    nodes: controller unit_agent
    environment: machine
  }
  positions {
    controller left-of unit_agent gap: 60
    controller align-middle unit_agent
  }
}
"""


class TestEnvironmentParsing:
    def test_environments_parsed(self):
        f = parse(ENV_SRC)
        m = f.models[0]
        assert len(m.environments) == 2
        names = {e.name for e in m.environments}
        assert "kubernetes" in names
        assert "machine" in names

    def test_environment_present(self):
        f = parse(ENV_SRC)
        m = f.models[0]
        k8s = m.find_environment("kubernetes")
        assert "controller_k8s" in k8s.present
        assert "unit_agent" in k8s.present

    def test_environment_abstracts(self):
        f = parse(ENV_SRC)
        m = f.models[0]
        k8s = m.find_environment("kubernetes")
        assert k8s.abstracts.get("controller") == "controller_k8s"

    def test_validates_cleanly(self):
        f = parse(ENV_SRC); validate(f)


class TestEnvironmentValidation:
    def test_unknown_present_node_rejected(self):
        src = ENV_SRC.replace("present: controller_k8s unit_agent",
                              "present: controller_k8s unit_agent bogus_node")
        f = parse(src)
        with pytest.raises(ValidationError, match="present node"):
            validate(f)

    def test_unknown_concrete_in_abstracts_rejected(self):
        src = ENV_SRC.replace(
            "controller: controller_k8s",
            "controller: nonexistent_node"
        )
        f = parse(src)
        with pytest.raises(ValidationError, match="concrete node"):
            validate(f)


class TestEnvironmentResolution:
    def test_k8s_view_resolves_to_controller_k8s(self):
        f = parse(ENV_SRC); validate(f)
        d = next(x for x in f.diagrams if x.name == "K8s view")
        m = f.get_model(d.model_name)
        layout = solve(d, m)
        # "controller" abstract id should resolve to controller_k8s
        assert layout.find("controller_k8s") is not None
        assert layout.find("controller_vm") is None

    def test_machine_view_resolves_to_controller_vm(self):
        f = parse(ENV_SRC); validate(f)
        d = next(x for x in f.diagrams if x.name == "Machine view")
        m = f.get_model(d.model_name)
        layout = solve(d, m)
        assert layout.find("controller_vm") is not None
        assert layout.find("controller_k8s") is None

    def test_k8s_view_renders(self):
        f = parse(ENV_SRC); validate(f)
        d = next(x for x in f.diagrams if x.name == "K8s view")
        m = f.get_model(d.model_name)
        svg = render(route(solve(d, m), m, d.select), m, d)
        assert "<svg" in svg
        assert "Controller pod" in svg

    def test_machine_view_renders(self):
        f = parse(ENV_SRC); validate(f)
        d = next(x for x in f.diagrams if x.name == "Machine view")
        m = f.get_model(d.model_name)
        svg = render(route(solve(d, m), m, d.select), m, d)
        assert "<svg" in svg
        assert "Controller VM" in svg
