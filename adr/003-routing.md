# ADR-003: Obstacle-aware routing over strips

**Status:** Implemented (0.26.0, 2026-09-18). All eleven decisions,
the discussion resolutions and the acceptance bar are landed; measured
results recorded in SPEC ("Geometry audit") and SESSIONS. One
measured tension at the acceptance bar: juju3 rotated labels 31 vs
the 30 baseline — the +2 rotated labels are the direct price of
eliminating crossings (the u_app3 mesh detour) and emergent pair
offsets; see SESSIONS "0.26.0" for the analysis. Everything else is
inside the bar: crossing-edges 0 (juju3) / 2 (juju4, both audited
residuals), label clashes 2/1, node strikes 1/4, sequences
byte-identical, turns/edge 0.40/0.99 with K=40.

## Context

The router is obstacle-blind: every route is derived from the two
endpoint rects alone (straight face-to-face for horizontal-dominant
edges, L-shaped for vertical, face spreading to de-clutter shared
faces). The measured consequences (0.25.2-0.25.4 audits, both twins):

- **Arrows over boxes** — the headline review defect ("fix ASAP"):
  juju3 15 crossing-edges, juju4 35 (the 0.25.4 gap-floor shrinkage
  tightened the auto-layout twin from 31). The HA Raft mesh's long
  arrows cross the middle controller's children in both twins; fan
  edges cross stacked column-mates; the controller worker tree's
  leader-lease edge plows through its own column-mates.
- **Border notches without port semantics** — `_compute_border_gaps`
  (renderer.py:279) notches a container border for ANY edge segment
  crossing it, with no ancestry check: an edge passing OVER the Charm
  container cuts notches into its border ("Charm box has its edge
  interrupted"). A notch is being drawn where no port exists.
- **Coincident anti-parallel strokes** — pairs sharing an endpoint
  pair overlap on one stroke; their labels are anchored at ⅓/⅔ of the
  span purely to keep the two texts apart (a workaround, 0.25.4).
- **Diagonals on horizontal planes** (juju3 11 / juju4 22): edges
  render face-centre to face-centre, so any vertical centre offset
  becomes a diagonal — including planes the author laid out flat.

The user's review framing, which this ADR answers:

1. Routing style is a **global** decision: curved vs L-shaped vs
   diagonal must be decided once, not per diagram.
2. **Minimize arrow length** — shorter arrows read faster.
3. L's tidiness **must not override meaning**: an L imposes two
   turns the model did not declare; the diagonal is content
   ("meaning lives in the diagonal"; "all roads lead to x" — hub
   structure — must stay preattentive).
4. **No Structurizr-style box explosion** — routing must not
   re-arrange or inflate the drawing to make room for paths.
5. State-view transition labels (horizontal with opaque masks, not
   along the curve) are the **same decision** — do not fix in
   isolation.

## Decision

**Routes are obstacle-aware shortest paths over strips, found by
search, not derived from endpoint geometry.** Specifically:

1. **Shortest path over a Hanan grid, diagonals allowed.** Candidate
   bend points come from the endpoint coordinates and the obstacle
   rect coordinates (Hanan grid); the search is A* with 8-neighbour
   moves, so a path bends only to clear an obstacle. This is the
   libavoid-free v1 the 0.25.2 plan already scoped. Diagonal edges
   are the default and survive routing (see 6).
2. **The search chooses exit and entry faces.** Anchor candidates
   come from the grid, not from closest-opposing-face pre-selection;
   `_best_anchors` retires into grid seeding. Author-declared anchors
   stay pinned (field-qualified endpoints are model content — author
   speech outranks heuristics). Face spreading becomes emergent:
   each later route sees earlier strips as obstacles and offsets
   along the shared face; the post-pass retires once measured on the
   corpus.
3. **The collision currency is the strip: path + label extent.**
   Every edge occupies a swept corridor — stroke width, arrowhead,
   and the one-sided ADR-002 label extent (text above the line). A
   route is collision-free only if its whole strip clears every
   obstacle: node rects, container walls, and other edges' strips.
   Labels never strike; routing never has to be re-done for
   labelling.
4. **Annotation boxes and regions are meta elements — never
   obstacles** (user decision, 2026-09-18). An annotation box is a
   human circling an area of the board for emphasis: a statement
   about the nodes it encloses, not a thing in the model. Edges cross
   annotation regions freely; annotation borders are never notched
   (notches are container-port semantics, decision 11 — the
   side-gap notch computation in `_render_ann_box` is deleted at
   implementation: a circling has no gates). Annotation boxes stay
   stroke-only (`fill=none`) and paint last, so a crossing edge is
   overlaid by a thin marker stroke and occluded by nothing.
5. **Cost = length + turn penalty, fixed per turn.** The search
   minimizes path length plus a per-turn constant K. K is a fixed
   pixel price, not scaled by edge length (see Resolved 1); it is
   tuned against the corpus, with turns-per-edge reported by the
   audit so the tuning is measured, not guessed. A diagonal is
   shorter AND has fewer turns, so cost keeps diagonals by default
   without special-casing. The turn constant should start high
   enough that a path only bends to clear an obstacle.
6. **Diagonal-preserving; L-shaped stays opt-in.** The directness of
   a connection is meaning: consumer→provider adjacency, hub reach,
   fan structure. The router must not flatten that into orthogonal
   tidiness. Declared orthogonal routing (the existing "straight by
   default, orthogonal opt-in" decision) becomes a 4-neighbour
   search with the same strip currency — one mechanism, two axis
   vocabularies.
7. **No box explosion.** The router treats the solved arrangement as
   fixed input (position is content): it never moves nodes, never
   inflates containers, never inserts gap floors to make room. When
   no collision-free path exists, the router returns the
   cheapest-collision path and reports it — audited, never silent
   (Resolved 3) — to the solver's label contract, which may reserve
   clearance and re-solve. The arrangement yields only through the
   solver, under the user's constraints, never through the router.
8. **Anti-parallel and mesh edges route at distinct offsets.** Edges
   sharing an endpoint pair (or a face) get separate corridors
   (decision 2's emergent spreading). The ⅓-⅔ label anchors become
   redundant and are removed: each label rides its own stroke.
9. **Rounded joins are a later aesthetic pass.** v1 ships polylines
   with `stroke-linejoin="round"` — one attribute, zero geometry,
   sub-pixel corners. True fillets (arcs in the path data) are
   deferred behind the acceptance bar and dropped if the corpus
   reads clean with polylines — the diagonal-preserving search bends
   only at obstacles, so corners are rare. If kept, fillet radius
   stays below the strip side padding, so rounding is provably
   clearance-safe. Rounding never participates in the search.
10. **State-view transition labels adopt along-path textPath under
    this decision.** Transition curves become routed strips like any
    edge (back-edge bows outside the machine are the same
    corridor-around-obstacle problem); labels ride the curve per
    ADR-002 and the opaque background masks die. One label mechanism
    across all three view kinds — decided globally, as reviewed.
11. **Port semantics for border notches.** `_compute_border_gaps`
    notches a container border only when **exactly one endpoint of
    the edge is inside that subtree** — the notch then reads as a
    port (the edge genuinely enters or exits there). Edges passing
    over a container (both endpoints outside) leave the border solid;
    their crossing is a routing defect for 1-8 to eliminate, not a
    border feature. Edges internal to the subtree do not notch
    their own container. Annotation boxes never notch (decision 4).

## Reasoning

**Why shortest-path search over strips rather than smarter
endpoint-derived routes?** Every current defect class comes from
routing in ignorance of everything but the two endpoints. Adding
obstacle awareness piecemeal (mid-y flattening here, detours there)
reproduces the placement-branch proliferation ADR-002 abolished for
labels. One search with one collision currency — the strip, which
ADR-002 already made uniform — handles crossings, coincident pairs,
label strikes, and state-view bows as the same problem: a strip
intersecting an obstacle.

**Why are annotation boxes not obstacles?** Because they are
commentary, not content (user, 2026-09-18): an annotation box is a
human circling an area of the board for emphasis — a statement about
the nodes it encloses, not a thing in the model. Making commentary a
wall inverts the relationship: the emphasized content would be
routing around the emphasis. The corpus proves the point — the
"Forced structure" regions span the containment hierarchy on
purpose, so every flow edge crosses them; a wall there is
unrenderable. The current rendering already fits the metaphor
(measured): annotation boxes are stroke-only (`fill=none`) and paint
last, so a crossing edge is overlaid by a thin marker stroke and
occluded by nothing. The one behavior contradicting the metaphor —
notching the annotation border where edges cross (`_render_ann_box`
side-gaps) — is deleted by this decision.

**Why preserve diagonals?** The review's own principle: meaning lives
in the diagonal. A hub whose spokes all reach directly reads
preattentively ("all roads lead to x"); the same spokes bent into
Ls read as a maze — tidiness overrides meaning. Diagonals are also
the shortest paths, so cost = length + turns keeps them by default
without special-casing.

**Why no box explosion?** Structurizr's router makes room by inflating
boxes and gaps until every edge is a tidy orthogonal; the result
teleports authoring intent (position is content — the model's spatial
argument is the diagram). ggarch's division of labor: the router
finds the honest best path through the given arrangement; the solver
(under user constraints, via the existing reservation machinery) is
the only thing that changes arrangement.

**Why fold state-view labels in?** Their masks exist because labels
float free of their curves; once labels ride paths (ADR-002) and
paths are routed strips (this ADR), masks solve a problem that no
longer exists. Deciding per-view would leave two label mechanisms
and mask machinery alive — the exact mode-duality ADR-002 removed.

**Why fix border notches here?** Notch semantics are port semantics,
and ports only make sense relative to routed paths: once routes are
obstacle-aware, an edge crossing a container it does not enter is a
router bug to eliminate; the border renderer must not paper over it
by notching. Landing it with the router makes the notch an honest
signal.

## Consequences

**Easier:**
- One collision currency (strip) across router, solver reservations,
  audit, and all three view kinds' labels.
- Crossing-edges and label-clash metrics become router-owned and
  measurable against an acceptance bar, not hand-compensated by
  authored positions.
- Anti-parallel pairs separate; ⅓-⅔ anchor workaround is deleted.
- State-view masks die; one label mechanism everywhere.
- Annotation boxes never constrain routing — cross-cutting regions
  stay crossable by design (Forced structure); their side-gap
  notch computation is deleted, and the audit's crossing metric
  (which already measures node rects only) needs no change, so the
  recorded baselines stand.
- The audit harness (segment-vs-rect, label-strike tests) already
  measures everything the acceptance bar needs.

**Harder:**
- A* over a Hanan grid of every-rect coordinates per view: needs
  measurement on the corpus (22 views; the largest has ~17 edges and
  ~40 nodes) before committing to the grid density and the turn
  constant. Risk: grid degeneracy in tightly packed containers.
- Pairwise strip-vs-strip collision makes the search order-dependent
  for meshes (route A's offset constrains route B); v1 routes pairs
  and fan-groups greedily after independent edges.
- "Cheapest collision" paths must degrade gracefully: residual
  crossings appear as audit lines (edge, obstacle, blocker) — the
  router must never distort a route to hide one.
- Sequences keep their own row-router — out of scope by acceptance
  (byte-identical), but the strip concept should stay compatible.

**Acceptance bar (from the 0.26 plan, revised by discussion):**
crossing-edges near zero in both twins over node and strip obstacles
(annotation boxes/regions are meta elements and do not count);
sequences byte-identical; rotated-label and label-clash counts no
worse than the 0.25.5 baseline; strips clear all node obstacles in
the audit; turns-per-edge reported so the turn constant is tuned,
not guessed.

## Resolved in discussion (2026-09-18)

1. **Turn constant: fixed K, no length scaling** (recommendation,
   adopted). The bend trade is local: around one obstacle the search
   compares two clear paths differing by local detour length and one
   bend; K is the exchange rate in pixels ("a bend is worth K px of
   detour"). Total edge length is irrelevant to that comparison, and
   scaling K with it makes long edges refuse bends and buy them back
   with detour length — backwards for "minimize arrow length". Bend
   count is naturally bounded (each bend must save ≥K px, and bends
   only occur clearing obstacles), so long-edge zigzag needs no
   special case; if the corpus shows one anyway, the staged fix is a
   per-edge turn budget (a legible constraint), not a continuous
   coupling. Grid: classic Hanan coordinates v1 (endpoints + obstacle
   projections, duplicates collapsed with a tolerance); refine only
   on audit evidence of forced crossings in packed containers.
2. **Annotation boxes are not obstacles** (user decision). Meta
   elements — a human circling an area for emphasis — never
   obstacles, never notched, never in the collision economy.
   Recorded as decision 4. This reverses the 0.26 plan's earlier
   wording ("annotation boxes count"); the audit never measured them,
   so the baselines are unaffected.
3. **Residual crossings: audited + reported, never a build failure**
   (recommendation, adopted). A crossing under authored constraints
   is a rendering-quality fact, not a model untruth — build failures
   are reserved for model lies (parse, validation). A hard gate would
   make valid authored views unrenderable and the corpus (15 authored
   crossings today) permanently red, inviting bypass. The router draws
   the cheapest-collision path honestly — the crossing is visible in
   the SVG by construction — and the audit reports every residual.
   The forbidden behavior is hiding, not failing.
4. **Anchor faces: the search chooses; declared anchors stay pinned**
   (recommendation, adopted). Closest-opposing-face pre-selection is
   endpoint-only geometry — the same obstacle-blind class this ADR
   retires; cost = length + turns is the honest arbiter. Recorded as
   decision 2.
5. **Rounded joins: post-pass; v1 = `stroke-linejoin="round"`**
   (recommendation, adopted). One attribute, zero geometry,
   sub-pixel corners; true fillets only if the corpus still reads
   harsh after the acceptance bar. Recorded as decision 9.

---

## Amendment 0.26.1 (2026-09-18, same day) — the route vocabulary

The post-release user review measured a TRACEABILITY regression the
acceptance bar could not see: monster detours (path/direct up to 8.8x),
weaves up to 7 bends, a spurious tail notch, near-corner grazing
entries. Root cause (measured, per edge, both twins): **decisions 1-2
made earlier edges' strips HARD obstacles in an open canvas, so any
collision-free path won however absurd.** The user's positions
supersede parts of this ADR:

1. **The route vocabulary replaces the search** (supersedes decisions
   1, 2 and 5's mechanism; keeps the K=40 exchange rate and decision
   6's diagonal stance): straight -> L (one bend) -> U (two bends,
   deliberate). No route exceeds two bends. Candidates are enumerated
   deterministically (face x ladder anchors with corner insets); the
   cheapest CLEAR candidate wins: cost = length + 40/bend + anchor
   reuse + label-strike costs. Curved lines are rejected as the
   general vocabulary (clearance on curves is not exactly measurable;
   the corpus defects never needed them). A U exists only where
   straight and L are node-blocked — "a deliberate shape where
   topology demands it" (e.g. node 1 -> node 3 around a TB stack).
2. **Node rects are the only hard obstacle** (supersedes the strip
   currency of decision 3): no crossing, no graze — exact segment-box
   distance, corner-tangency-safe. Annotation boxes/regions stay meta
   (decision 4 stands). Field-qualified anchors stay pinned.
3. **Soft strips / penalized grazes are REJECTED** (user position).
   Separation is deliberate offsets: reused face anchors cost more
   than a fresh ladder slot ("offsets are not bends"), so fans, meshes
   and anti-parallel pairs spread deterministically. Residual
   edge-over-edge overlaps are audited, never routed around; their fix
   is layout.
4. **No grazes and no node crossings** (user position): the audit's
   traceability block (per-edge path/direct ratio, turns histogram,
   >2-bend count) makes the class measurable; crossing-edges stayed at
   zero and node strikes fell to 0/1.
5. **Layout-first**: the shortest honest arrow usually comes from the
   arrangement. The floor now layers by longest-path depth over the
   whole visible DAG (dagre-grade; a declaration-order one-pass had
   manufactured the juju4 "Data model" 5.36x monster), and fan columns
   align toward their anchor (centre-aligning unequal members inflated
   containers symmetrically). Auto-layout targets dagre/Mermaid
   quality; position stays content.
6. **Tail-notch epsilon**: a border crossing within epsilon of a
   segment endpoint is the anchor itself, not a crossing (the
   kiwisolver ~1e-13-inside seed no longer cuts a spurious notch).

Measured (0.26.1): juju3 max-ratio 8.76 -> 1.86, >2-bend 5 -> 0,
strikes 1 -> 0; juju4 max-ratio 5.36 -> 2.06, >2-bend 15 -> 0, strikes
3 -> 1 (forced, audited); crossing-edges 0/0; sequences byte-identical.
The strip-crossing/residual counts are now edge-over-edge overlaps —
audited facts of retiring hard strips, owned by layout.

## Amendment (2026-09-21): border rides are hard-banned

Reviewer position, measured on the corpus: an edge whose first or last
leg is collinear with a node's own face line rides the border before
meeting the face (worker tree, domain_services -> db_accessor: 30px up
the target's west border; the same class at 6px in the authored view).
"It looks wrong" — the vocabulary now guarantees a perpendicular
approach or a corner landing:

- Candidate forms whose endpoint rides are corner-snapped at
  evaluation: the riding endpoint slides to the face-span end nearest
  the penultimate point, so the stroke arrives from outside and lands
  at the corner (`router._corner_snap`).
- Any ride the snap cannot collapse (the endpoint already sits at the
  span end) is priced at RIDE_COST (400px) — above every legitimate
  cost bundle — so any ride-free candidate wins; a ride survives only
  when the alternative is a crossing or no route.
- Pinned (field-qualified) anchors are content and do not snap; their
  L orientations are filtered to ride-free forms directly.
- The audit gains the `border-rides` metric as a hard gate invariant
  (collinear overlap of a first/last leg with any face line).

Measured corpus-wide: 15 rides (5 views, incl. 2 authored) -> 0; the
gate holds (crossing-edges 0, node-strikes 0, wall-crossings 0,
>2-bend 0).
