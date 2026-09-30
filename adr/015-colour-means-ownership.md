# ADR-015: Colour means ownership; one node shape; kind is a badge

Date: 2026-09-29 (session 73, PR 4 of the 4.1 docs split). Status: **ACCEPTED** -- the
reviewer's directives during the PR 4 work ("keep all juju thingies for now represented
simply through an orange border", "no entity should have any fill", "I want a color switch
to mean something", "let's make all ggarch nodes the same shape -- a rounded rectangle --
then use badges for ggarch node kind"). Worked ground: ggarch 0.1.0 commits b75f31b,
f4bcba6, 04899ca, ba07b99, 0ab77b2, 6bfab23 and the `deployed` badge.

## Context

The juju preset carried node identity through overlapping channels: fill, border hue
(orange for Juju software, brown for containers, amber for records and databases, green for
infrastructure, purple-grey for units), shape (person, cylinder, box) and a corner badge
(an orange J, an empty square for charms, an amber table). Two oranges ~90% identical
(#C74210 and #E95420) read as noise, the badges were hard to read at 14px, and the fills
made light and dark renders diverge. The reviewer wanted a coherent visual grammar and
preferred a bare minimum until one exists.

## Decision

1. **Colour has one meaning: ownership.** An orange (#E95420) border marks Juju machinery
   (juju-software, charm, node, unit, pebble, database, record). One grey per mode marks
   everything outside Juju (person, external, workload). Persistence edges (data, records)
   and the records chip take the Juju orange. No other hue exists in the preset.
2. **No fills, transparent canvas.** Nodes are unfilled and the diagram paints no canvas
   background in either mode, so the page shows through. Text and stroke colours still switch
   per mode. Sequence lifelines are masked around self-call labels and activation bars
   instead of being hidden by opaque rectangles.
3. **One node shape.** Every node is a rounded rectangle. Kind is a corner badge:
   the Juju mark (the glyph from the Juju logo) on juju-software, the person icon, a
   cylinder on database, the table mark on record. Plain boxes carry no badge.
4. **The four channels.** Border colour says who owns it; border dash says lifecycle
   (solid persistent, dashed init, dotted ephemeral); corner badge says kind; edge dash and
   arrowhead say interaction (ADR-004).
5. **`container` is `node`.** In Juju a node is a machine or a pod, and machines nest (a
   LXD container on a VM is a machine inside a machine). The preset keeps `container` as an
   alias so existing models render unchanged.
6. **Collectives** draw their stack as full rounded outlines with the front box masked out
   (never as filled or square-cornered layers) and may contain children.

## Consequences

- The geometry audit is unchanged (juju.ggarch of the prep branch: 553 edges, 0 crossing
  edges, 0 node strikes, 8 label clashes, before and after); the change is colour, badges and
  canvas only.
- The Sphinx modal needs dark rules for pages in "auto" theme (6bfab23): with a transparent
  canvas the modal's own background decides how a diagram reads.
- ERD end-label halos, generalization triangles and the legend still fill with the canvas
  colour; none is used by the architecture diagrams. Revisit when an ERD view runs on a page
  whose background is not white or #1E1E2E.

## Decided: notation for a deployed entity

"An application deployed on a node from a cloud" reads differently from a bare one through a
`deployed: true` node attribute that draws a small cloud outline in the top-right corner, in
the node's border colour (top-left carries kind, top-right carries where it runs). Orange for
Juju-managed, grey for the same thing before Juju; instances and collectives inherit it. Chosen
over a double border, which needed an inner box that stayed empty in collapsed views and
crowded the collective stack (prototyped and compared, 2026-09-29; the reviewer: "yes").

## Amendment (2026-09-30, session 74): a visible grey, and the entity kind

- The single grey had become too shy on the docs pages: #AAAAAA (2.3:1 on white) and #666666 (2.9:1 on #1E1E2E), drawn one pixel wide. The
  preset now uses #8A8A8A in light mode (3.4:1) and #A3A3AD in dark mode (6:1), and dark mode draws every node border at 1.5 so that orange and
  grey keep equal weight. The geometry audit is unchanged (it does not depend on colour or stroke width).
- New node kind `entity`: an orange border drawn dotted, no badge, for the logical entities Juju keeps (a model, an application), so that they read
  differently from software (solid orange, with the Juju mark) and from people and workloads (grey). The dash still means lifecycle for other
  kinds; for `entity` the dotted border means "an abstraction, not a process".
