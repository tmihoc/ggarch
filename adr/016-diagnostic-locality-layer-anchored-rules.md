# ADR-016: Diagnostic locality: rules and errors anchor inside their layer

**Date:** 2026-09-30 (session 76, a Claude Code session on the juju repo)
**Status:** Accepted (reviewer direction, 2026-09-30; machine.md is the pilot, draft in `~/git/misc/juju-reference/machine-rewrite-draft.md`)

## Context

ADR-011 (session 33/34) ended with entity pages shaped as the DPE chain spine
plus one section outside it, *X rules and errors*, holding "the enforcement
surface ONLY": claims not stated at their stage, plus the error taxonomy.
In the prep branch's machine.md that section appears three times
(`machine-declaration-rules`, `machine-persistence-rules`,
`machine-execution-rules`), each a flat Rules list and a flat Errors list at
the bottom of its layer.

Reading those lists as a user holding an error string shows the cost: the
reader finds the error in a list, then has to work out where in the page's
material it arises. The storage-optimised list (what the code defines) does
not serve the consumption path (what the reader is looking at when it
happens). A reviewer-run iteration with another model proposed anchoring each
rule and error at the place it occurs. Checking that draft against the 4.1
source (session 76) confirmed the idea and exposed why it cannot be done by
reshuffling text: several errors sit in the wrong layer in the prep page
(see Consequences).

## Decision

1. **Diagnostic locality.** A rule, an error, its trigger and its remediation
   appear once, beside the thing they constrain. There is no free-standing
   rules-and-errors list. Supersedes ADR-011 item 5's "rules-and-errors = the
   enforcement surface ONLY" and the standalone *X rules and errors* h2s
   (ADR-013's "outside the chain" clause).
2. **The anchor differs per layer.**
   - Declaration: by lifecycle action (create, designate, consume, remove).
   - Persistence: by stored record component (primary entry, parent record,
     cloud instance record, status records, lookups).
   - Execution: by operational loop (controller-side provisioning, agent-side
     provisioning, removal, watchers).
3. **Filing follows the raise site.** An error belongs to the layer whose code
   raises it, found in the Go source, not to the layer whose prose first
   mentions it. The domain `errors.go` constants and the `Add(...)` /
   `%w` sites are the authority. (ADR-011 item 4, "one claim, one stage, one
   section", now includes errors.)
4. **Item shape.** `**Name:** description.` then, nested: `*Rule:*` and
   `*Related error:*` with `**`error string`** - *Trigger:* ... *Remediation:* ...`.
   The error string is the literal Go message. A status value (for example
   `provisioning error`) is a value of a status record, not an error: it
   goes with its record, never under *Related error*.
5. **Fidelity.** Keep every verified fact, link and error string; drop or
   correct what the source does not support. Anchors (`(x-declaration-rules)=`
   and similar) are preserved verbatim by stacking them on the place the
   content moves to (ADR-014 discipline), because other pages link to them
   (`machine-execution-rules` is referenced from the watcher page).
6. **Sentence case** for bullet titles, rules, triggers and remediations.
7. **Scope.** The form applies to entity pages whose layers are real (ADR-013
   types 1 and 2). Where a layer is empty, the page says so in one sentence
   and no bullets are invented. Other reference types keep their own forms.

## Reasoning

- Alternative kept from ADR-011: a dedicated rules section per page. It
  satisfies "one place", but fails the locality test above and was already
  split three ways by layer in the prep pages.
- Alternative: one action anchor for all layers (the first draft). Rejected
  in the pilot: a schema does not run a lifecycle, so persistence bullets
  phrased as actions read as false procedure. Record components are the
  honest unit there.
- Anchoring by raise site (item 3) is what turns the restructure from a
  cosmetic move into a correctness pass.

## Consequences

- **Errors in the wrong layer become visible.** In the machine pilot
  (verified against 4.1 source, session 76):
  - `grandparent machine are not supported currently` is raised only in
    `domain/machine/state/reboot.go`: it is an execution-layer (reboot)
    error, not a declaration error.
  - `machine already exists` is raised only on the model-import path
    (`domain/machine/state/migration.go`): it is not a creation error.
  - `invalid container type` is raised when a model's container constraint
    holds an unknown value; 4.1 knows `lxd` and `none` only, so "check the
    cloud's supported container types" is wrong.
  - The container nesting cap is enforced by name validation
    (`core/machine/machine.go`: more than two slashes gives "machine name %q
    has too many containers"), not by the grandparent error.
  - `machine constraint violation` exists but is raised in one place: setting
    constraints on a provisioned machine whose recorded arch differs from the
    required arch. Only arch is compared, so "reported hardware must satisfy
    the constraints" overstates it.
  - The dead-transition rule is precise in the removal service:
    `entity still alive`, `machine has containers`, `machine has units`,
    `machine has storage`.
  - `provisioning error` is a status value, not an error; its retry sentence
    has no support found in the source and is held out until verified.
- Every entity page in ADR-013 types 1 and 2 needs a raise-site pass, which
  costs one source check per error. The pages become longer in the layers and
  shorter overall (no fourth section).
- The ggarch catalogue's Insert-at strings that point at the old
  rules-and-errors headings must be re-pointed per page.
- Do not generalise from the machine draft's prose: the first pass
  (another model's rewrite of the prep page) also dropped two rules, four
  anchors and one error string. The checklist is in `juju-reference/`.

## Rollout (session 76, same day)

The form was applied to all 24 entity pages (types 1 and 2 of
`~/git/misc/juju-reference/reference-page-types.md`, plus zone converted from
the old umbrella) on the branch `4.1-docs-entity-reference-layers` (worktree
`~/git/misc/juju-entity-ref`, 25 commits, unpushed). Findings:

- **The raise-site pass corrected the prep pages in every layer**, not only the
  machine pilot: `user unauthorized` is a wrong or missing password (not missing
  permissions); `user authentication disabled` is raised on password, activation
  key and grant writes; `action not defined for charm` is raised at enqueue
  (declaration), not at start; `machine constraint violation` compares the
  architecture only; `quota limit exceeded` names two different errors (relation
  endpoint capacity, application configuration size); the credential "invalid is
  rejected" rule has no code behind it.
- **Facts that had gone stale for 4.1:** storage detachment is implemented
  (`juju detach-storage`); the S3 object store is configured through the
  object-store domain, not controller config keys; `juju enable-ha` is gone but
  the `EnableHA` API call remains; a migration target must be 4.1 or newer
  (`internal/migration/precheck.go`); export-bundle exists and returns a
  not-implemented error; the zone list is cached in the model database.
- **Duplicated claims were filed once:** the machine-constraint errors live on
  the machine page (the constraint page links), `cloud still in use` on the
  cloud page, and `permission not found` / `permission not valid` on the access
  page.
- **Mechanics that worked:** a script that resolves each error string to its Go
  constant and raise sites (`juju-reference/tools/raise_sites.py`), and a shingle-based fidelity check
  of every prep sentence against the new page (`juju-reference/tools/loss_check.py`). The fidelity
  check caught three truncations in pages written from clipped previews; read
  source pages in full.
- **Diagrams are deferred:** 41 `{ggarch}` fences were removed (listed in
  `juju-reference/fence-manifest.md`); 4.1's `docs/juju.ggarch` holds only the
  architecture views, so each entity view must be ported and verified against
  the 4.1 schema in its own pass.
- **`watchers` needed a page:** every entity page links it; `watcher.md` was
  added (verified) and the reference index lists it.

## Amendment 2026-10-19 (PROPOSED): error shapes, operation bullets, generated index

Derived in `~/git/misc/juju-reference/entity-page-form-v2-proposal.md` from the
migration howto comparison (`error-inventory-vs-howto-troubleshooting.md`). Not
yet applied to any page. Items 1 to 7 of the Decision stand; these are added:

8. **Errors are always a table, rules stay prose.** Under their bullet, errors
   go in a `{list-table}` (message as seen, trigger, remediation); no count
   threshold, so a page's shape does not change when an error is added. Tested
   nested inside bullets. A hand-written table has no source column; the code
   path is a maintenance fact and is carried by the generated index.
9. **Three message kinds.** Constant (the literal Go message), composed
   (`<prefix>: <inner>`, documented once on the loop that composes it) and
   passthrough (one row per source; no inventory). Templated messages show
   `<placeholders>`.
10. **Operation bullet.** A task that crosses entities (migrate, remove, deploy,
    upgrade, integrate) gets one execution-layer bullet on the owning entity
    page: the phases in order, the status message per phase, and a failure
    table with a Phase column, rows in the order the failures occur. Messages
    raised by the operation's own code are owned by that table; constants raised
    in other domains stay on their entity pages and appear as a link. The
    declaration layer's bullet for the operation links to it.
11. **Generated error index.** `docs/reference/error-index.md`, generated from
    the Go `ConstError` definitions (message, domain, constant doc comment as
    trigger, source path) joined by message string to the page that documents
    it; undocumented constants show as gaps; an allowlist marks internal ones.
    A CI check keeps it current, like the generated CLI pages. Linking
    granularity is the containing section.
12. **Howtos point, never restate.** A howto troubleshooting entry is keyed by
    the message as seen, says what to do next and links to the reference row;
    a multi-step fix stays in the howto as a procedure.
13. **Completeness claim.** The form guarantees completeness for Go constants
    (the index proves it) and for the messages of documented operations
    (maintained by hand, rechecked when the operation's code changes), and
    claims nothing for passthrough errors.

Rollout order, by undocumented constants times user frequency: model migration,
removal, cross-model relations, then deploy and upgrade. One follow-up PR per
operation, each carrying the reference rows and the howto pointer together,
after #23451 merges.
