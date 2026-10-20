from ggarch.parser import parse
from ggarch.model import mask_fields

SRC = '''
model "S" {
  nodes {
    parent [type: record, label: "parent"] { fields { uuid [label: "uuid", type: "text", pk: true] } }
    child  [type: record, label: "child"] { fields {
      id [label: "id", type: "int", pk: true]
      parent_uuid [label: "parent_uuid", type: "text", fk: true] } }
  }
  edges { child.parent_uuid -> parent.uuid [type: data] }
  style { extends: juju }
}
diagram "D" from "S" {
  select { nodes: parent child
           edges: type data
           fields: hidden }
  positions { child right-of parent gap: 60
              child align-middle parent }
}
'''


def test_fields_hidden_masks_fields_and_keeps_cardinality():
    f = parse(SRC)
    assert f.diagrams[0].select.hide_fields is True
    masked = mask_fields(f.models[0])
    assert all(not n.fields for n in masked.nodes)
    edge = masked.edges[0]
    assert edge.card == (False, True, False, False)   # many child, one parent
    assert edge.source_field == "" and edge.target_field == ""
