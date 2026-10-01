# RUINFORM V1 — Branch Evolution checkpoint

**Date:** 2026-09-30  
**Status:** V1 continues. V2 remains a separate future route and must not interrupt V1 stabilization.

## 1. Architecture decision

The working architecture is:

- **Higgsfield app = frontend / interaction layer.** Uploads, controls, prompts, branch selection, archive/explore, progress, AI Mind UI.
- **Render `ruinform-intelligence` = intelligence/backend.** Material reading, Design Brain, branch/evolution contracts, futures, rendering orchestration, quality gate, build logic.
- Do not duplicate creative intelligence in the Higgsfield frontend. Frontend should collect intent and display state; Render should decide.

Goal for V1: make the existing flow reliable and intelligent before building the separate V2 CRM-like workspace with the AI Master agent.

## 2. Product decisions locked today

### V1 stays active
We explicitly decided not to replace the current frontend now. Finish V1 first. V2 will be a new route later.

### V2 is parked, not abandoned
V2 concept remains:
- CRM/workbench-like project workspace;
- numbered expandable stages;
- persistent AI Master agent that understands project state and can take actions;
- welding woman remains the visual/ad face of RUINFORM;
- AI Master helps with questions, actions, evidence collection and service improvement.

Do not let V2 work derail V1 until the V1 branch/evolution loop is stable.

## 3. Core V1 flow we are stabilizing

`MATTER -> ANALYZE -> IMAGINE -> EVOLVE -> BUILD -> VERIFY -> ARCHIVE/EXPLORE`

Critical concept:

> An archived generated object is not raw evidence anymore. It becomes a parent design/form with lineage. A branch adds NEW MATTER to that parent and evolves it.

Desired branch flow:

`LOCKED PARENT FUTURE + NEW MATTER + OPTIONAL USER INTENT -> DESIGN BRAIN -> 2 EVOLUTION FUTURES -> RENDER -> QUALITY GATE -> BUILD`

## 4. Branch bugs found and fixed today

### 4.1 Parent state was being lost after a new READ
A new Material Eye read could rebuild project state and lose `creative_intent` / branch meaning.

Fix direction implemented: preserve/reapply branch creative intent and parent contract after material analysis.

### 4.2 Frontend cleared the new branch upload
After `ADD TO BRANCH`, frontend state could visually lose the new uploaded matter.

Fix direction implemented: keep new matter visible/persistent through branch analysis.

### 4.3 Parent future was not visually/prompt-wise strong enough
`USE AS BASIS` did not sufficiently lock the selected generated object as the design ancestor.

Fix direction implemented:
- `ARCHIVE BASIS · LOCKED`;
- parent image remains visible;
- parent future has a persistent contract;
- new matter must not replace the parent.

### 4.4 Old source evidence leaked back into active branch ingredients
This produced the important failure where a pink tricycle wheel reappeared in `Pink Aperture Valet` even though the user had only added a new yellow/gold item.

Root behavior:

`parent future + old original evidence + new matter -> AI`

This was wrong.

Correct behavior now:

- **Old original evidence = provenance/history only.**
- **Parent generated ART = locked design ancestor.**
- **Only newly uploaded branch evidence = active new physical matter.**

The old five source objects must never become active ingredients in a later branch unless the user explicitly re-adds them.

### 4.5 Branch screen had scroll/state UX failures
The left column became taller than the viewport and `ADD TO BRANCH` became unreachable. The center also looked like a fresh project after uploads.

Fix direction implemented:
- independent scroll in the left column;
- long Future/menu can scroll;
- parent remains visible as locked parent form;
- new evidence is shown separately.

### 4.6 Future menu covered generated output
`HIDE MENU / OPEN MENU` is needed so the user can inspect the render without overlays.

Keep this behavior.

## 5. Major Design Brain insight today

We found the main conceptual error in branch evolution.

Old implicit instruction was too close to:

> Preserve the parent object/silhouette and add the new thing.

That causes decoration and attachment instead of design evolution.

New principle:

> **PRESERVE IDENTITY, NOT EXACT GEOMETRY.**

The parent future is **design DNA**, not frozen geometry.

New physical matter is **material/component inventory**, not a sacred intact object.

The AI may use a real object in multiple physically plausible ways:
- cut;
- bend;
- slit;
- drill;
- pierce;
- flatten;
- fold;
- trim;
- split into useful parts;
- disassemble confirmed components;
- use only a useful subcomponent;
- recombine parts;
- rotate/reorient/reform it.

Examples:
- umbrella -> handle, shaft, ribs, fabric if those parts are confirmed;
- flashlight -> shell, lens, reflector, cap, etc. if visible/confirmed;
- metal lid/disc -> ring, bent guide, cut plate, slot, partial arc, multiple strips, etc.

Never invent hidden components as known fact.

## 6. Anti-lazy evolution tests

Two important critic ideas were added/locked conceptually:

### REMOVAL TEST
Mentally remove the newly supplied matter.

If the parent future is essentially unchanged, the evolution is too weak and should be rejected/reworked.

### GENERIC SUBSTITUTE TEST
Ask whether the newly supplied object could be replaced by any generic plate/ring/decoration without changing the idea.

If yes, the concept did not understand the specific material/object strongly enough.

These are meant to stop results such as `Bowl Eclipse`, where a gold disc was simply placed behind the spoon-chain object.

## 7. Important behavior lesson: why AI kept using only ~2 objects

Earlier, Design Brain often chose only two source objects. This was not necessarily a bug. The system preferred a minimal coherent set instead of using every supplied item for compliance.

Separately, the branch evidence leak later allowed an old tricycle wheel to reappear unexpectedly. These were two different phenomena.

Current rule should remain:

> Do not force the AI to use every available object. Use the smallest coherent set needed for a strong concept, but every material that IS selected must have a meaningful role.

Never reward ingredient count for its own sake.

## 8. Explore / archive direction

Explore is now part of the real product loop, not just a gallery.

Expected behavior:
- user can revisit their generations;
- later public/community Explore can exist;
- `USE AS BASIS` creates a lineage branch;
- parent generation and material history stay attached;
- user adds only new matter to evolve it.

Object Passport is a separate future feature. Do not confuse it with the creator/user passport. The current creator passport page is not the object passport.

## 9. Current test object: Frozen Pour Valet

Parent future:

**Frozen Pour Valet**

> A short chain appears to pour from a tilted spoon, solidifying mid-fall into a small wall-mounted key hook.

Important design identity anchors:
- spoon;
- chain / frozen pour;
- terminal hook;
- suspended / restrained relationship;
- visual illusion of a pour becoming hardware.

Potential conceptual story discovered today (do NOT hard-code globally):

> The spoon on a chain can read as an image of dependence / consumption / humans being chained to appetite or food.

This can later become part of this object's **Object Story / Provenance / sales narrative**, but should not become a global prompt that forces every future to repeat the metaphor.

## 10. Gold-disc branch test

New matter: yellow/gold circular metal-looking pieces/discs.

After the branch contamination bug was fixed, Design Brain produced two relevant concepts:

### Last Drop Dish
> The silver chain-pour lands in one horizontal gold disc, which becomes a restrained coin-and-ring catch beneath the original hook.

Assessment: understandable and functional, but still too additive. The parent could remain nearly unchanged.

### Gravity Orbit
> One intact gold disc bends the inherited chain-pour into a precise orbit before it returns to the original key hook.

Assessment: stronger. The new matter changes the trajectory and spatial logic of the inherited chain rather than merely decorating it.

`Gravity Orbit` was selected for rendering.

## 11. Gravity Orbit render result

The Render result was a meaningful improvement:
- Frozen Pour Valet remained recognizable;
- the gold disc became integrated into the chain path;
- the chain wrapped around it before returning to the hook;
- old unrelated source objects did not reappear.

This confirms that the corrected branch lineage is working.

However, the result is still not final-quality because:
- the gold disc remained too literally an intact lid/disc;
- the chain mostly wrapped around it instead of being truly redirected by transformed material geometry;
- the interaction reads as `chain around disc`, not yet a strong engineered/sculptural `orbit`;
- the new matter participates, but is not transformed boldly enough.

Current verdict: substantial progress, but not WOW yet.

## 12. Better target generated during discussion

A better reference version was generated in ChatGPT after reviewing the Render output.

Desired geometry/behavior of that reference:
- retain the spoon + chain + terminal hook identity;
- transform the gold disc into an **active orbital guide / pulley-like sculptural element**;
- the disc is no longer a flat decorative lid;
- it can be cut/slotted/bent/recessed/formed;
- the chain clearly passes through/around a formed channel in the gold element;
- the gold piece visibly causes the trajectory change;
- the result remains physically plausible and gallery/product-photo clean.

This better reference is the immediate visual target for the next iteration.

## 13. Key distinction to teach the Brain next

For new branch matter, distinguish three levels:

1. **ATTACH** — simply place/add the object. Lowest-value fallback.
2. **TRANSFORM** — physically modify/decompose the new matter.
3. **INFLUENCE** — the new matter changes the geometry, tension, function, motion/path, negative space, or meaning of the parent future.

For serious EVOLVE concepts, prefer **TRANSFORM + INFLUENCE** over simple ATTACH.

A branch should not be considered strong merely because the new item is visible.

## 14. Next backend/design-brain changes to consider

Do these in Render intelligence, not as frontend hacks.

### A. Evolution contract
Make the contract explicitly state:

- preserve parent **identity anchors**, not exact placement;
- allow meaningful silhouette/geometry changes;
- new matter may be materially transformed;
- new matter should produce a causal change in the parent form;
- avoid simple `behind / beside / underneath / attached as accent` solutions unless functionally essential.

### B. Candidate diversity
For two Futures, aim for genuinely different evolution strength, e.g.:
- Future A: controlled evolution;
- Future B: more radical but still lineage-faithful evolution.

Do not just paraphrase the same attachment idea twice.

### C. Pre-render critic
Before spending an image render:
- run REMOVAL TEST;
- run GENERIC SUBSTITUTE TEST;
- check whether new matter is merely intact decoration;
- check whether parent identity anchors are still legible;
- require at least one meaningful causal relationship between new matter and parent.

### D. Render Director
If the text Future is strong but the image becomes literal/weak, then adjust the render-stage prompt separately:
- permit explicit physical transformation of the new matter;
- describe the interaction geometry;
- reinforce parent visual reference;
- do not let the image model simplify transformed matter back into an intact stock object.

This is where the generated better `Gravity Orbit` reference should guide us.

## 15. Tomorrow: exact continuation point

Do NOT restart from architecture discussions.

Start here:

1. Open the gold-disc `Gravity Orbit` test and compare the existing Render image against the stronger reference described above.
2. Improve **EVOLVE / Design Brain contract** so the new matter is allowed and encouraged to transform materially.
3. Improve the pre-render critic so intact decorative additions are rejected earlier.
4. Re-run the same branch first:
   `Frozen Pour Valet + gold disc`.
5. First inspect the **two textual Futures** before rendering.
6. Render the stronger one.
7. Success condition: gold matter visibly changes the chain-path/mechanics and is not merely a stock lid behind/inside the chain.
8. After this succeeds, test a second scenario with a different type of evolution:
   - chair/coil object + cushion (obvious additive/function case), or
   - umbrella/flashlight decomposition (component/deconstruction case).
9. Only after branch evolution is consistently strong move to **REALITY / BUILD GATE**: prove we actually know how to cut, bend, drill, weld, fasten and what must be bought.

## 16. Things NOT to change yet

- Do not start V2 implementation now.
- Do not move creative intelligence into Higgsfield frontend.
- Do not re-enable old source evidence as active branch ingredients.
- Do not force use of every source object.
- Do not hard-code the food/consumption metaphor globally.
- Do not weaken the quality gate just to unlock BUILD.
- Do not solve poor Future ideas by endlessly tweaking the image renderer; fix the idea stage first when the concept itself is weak.

## 17. Definition of success for V1 EVOLVE

A branch is successful when a user can look at the new result and immediately understand both:

1. **what object it descended from**, and
2. **why the newly introduced matter changed its future**.

If the new matter can be removed with almost no conceptual loss, the evolution is not finished.
