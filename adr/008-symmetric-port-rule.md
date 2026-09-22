# ADR-008: The symmetric-port rule — anchors distribute about the face midpoint

**Status:** Executed (2026-09-22, ggarch fd0e2f4). Lands the where-on-
the-face layer — the proposal the reviewer ratified on the 2026-09-21
floor review ("every multi-edge face distributes symmetrically about
its midpoint; the metric hard-gates zero anchors outside {midpoint,
symmetric slot, pair-bias, field pin, shape corridor}").

## Context

The session census (SESSIONS Addendum 23) measured 74 unexplained
anchors in juju.ggarch — non-fan multi-edge faces distributing by the
anchor-reuse ladder, shape corridors, and the corner stacks. The
flagship defect: **two same-sign arrows shared user_rec's bottom-right
corner at (183.2, 183.2)**. That corner is the border-ride hard law's
sanctioned landing (a leg collinear with a face line collapses to the
face-span end), yet two edges sharing one anchor violated both SEED_INSET
("anchors stay clear of face corners") and the reviewer's fan
distribution rule.

## Decision

For every face with ≥2 drawn anchors:

1. **Port sets, always including the axis.** The router pre-computes,
   per multi-edge face, the symmetric slot set `{mid}` ∪ `{mid ± (2i+1)d/2}`
   (even count) or `{mid}` ∪ `{mid ± i·d}` (odd), `d = min(PORT_GAP,
   usable/(n−1))`. The **axis (the midpoint) is always a member**, so a
   spine/align arrow holds the row axis straight (worker-tree columns
   stay vertical) while fan/peer edges take the slots.
2. **Candidate bound.** A face with a port set admits ONLY its slots as
   anchor candidates. The corner landing (the ride-law's span-end) is
   not admissible there: the ride collapse lands on the nearest slot,
   or drops the candidate (`SNAP_SKIP`) and the honest perpendicular
   L/U from a slot wins.
3. **Straight-ride rejection (`_leg_rides`).** A straight collinear with
   an endpoint border is a ride and is rejected — the free-path
   vocabulary loop previously only ride-checked L/U legs (a CMR straight
   rode both endpoints' top borders once the sets made it cheapest).
4. **Corner-safe port closure.** A corner anchor lies on two faces; the
   400px port exclusion must record/check every face within eps, or a
   stacked pair slips it (the recorded 'right' vs enumerated 'bottom'
   mismatch).
5. **Label-aware escape.** The set is the tightest symmetric spread;
   when a set-bound result's label strip clashes an earlier label strip
   (labels NEVER overlap, 2026-09-21), retry unrestricted and keep the
   clash-free result — the wider spread is still symmetric about the
   midpoint, so it stays principled.
6. **Declared fan constraints excluded** (ADR-007): the author's fan
   spacing owns its ports; the generic PORT_GAP pitch must not rebind a
   declared fan (measured: the refined cloud pair's labels clashed).

## Measurements (ggarch fd0e2f4, juju.ggarch)

- Census unexplained anchors: 46 → **18**. The user_rec corner stack is
  gone entirely.
- The 18 remaining: the worker-tree dense class (ADR-003 layout owner,
  ~11 anchors), free-standing asymmetric pairs (cloud_rec.right,
  lease_manager, primary_flag), and off-set label seats — each named in
  the review page.
- **Corner anchors are NOT new**: 23 at baseline (e2eafa7) → 24 now.
  They pre-date the rule (the ride-law's span-end remedy + the L/U
  vocabulary's span-end entries). Split into their own census class
  (`corner seat`, 8 single-face + 16 on multi-edge faces) so the
  reviewer sees them; verdict owed (accept the remedy vs inset the
  span-end landing by SEED_INSET).
- 379 tests green (3 new port-set regressions); `make check-ggarch`
  PASS; worker-tree align rows byte-identical to baseline.

## Consequences

- The measurement gate lives in `scripts/anchor-census.py --gate`
  (exits 1 on any unexplained anchor). A gate run today fails on the
  18 residual — the dense-web block needs its ADR-003 exemption list
  or a layout-layer fix before the gate is wired into check-ggarch.
- The singular `corner seat` class separates "principled seat" (the
  reviewer's corridor seats) from "ride-law remedy" so the page can
  present the real count. Its verdict is queued with the 4 LCLASH
  pairs (defect-or-tightness).
