# RUINFORM PRODUCT BRAIN

Single product-memory ledger for ideas, decisions, systems, experiments, parked work, and completed work.

_Last checkpoint: 2026-10-01_

## Status flow

`INBOX → APPROVED → DESIGNED → BUILDING → TESTING → DONE`

Use `PARKED` when the idea is good but intentionally deferred.

---

# PRODUCT THESIS

RUINFORM turns real discarded or existing matter into new designed futures, then preserves the object's provenance, meaning, lineage, verification state, and ownership in an Object Passport.

The product should feel like an AI design studio first — not a generic image generator and not a heavy engineering CAD tool.

Core creative loop:

`SEE → IMAGINE → RENDER → BRANCH / EVOLVE → EXPLORE`

Light V1 making bridge:

`MAKE PLAN → SIMPLE MAKER CUES → VERIFY`

Full engineering remains V1.5 Experimental.

---

# OCT 12 HACKATHON CHECKPOINT

Colosseum Crypto World's Fair submission deadline: **2026-10-12**.

Hackathon goal: ship the smallest complete story that proves RUINFORM can become a venture-scale product.

## Demo story that must work end-to-end

1. User uploads real matter.
2. RUINFORM reads the matter.
3. RUINFORM proposes two materially and conceptually distinct Futures.
4. User selects and renders one Future.
5. User can evolve it through Branch / Evolve with new matter.
6. RUINFORM creates an editable Artist Mind meaning layer.
7. Accepted work becomes an Object Passport with provenance + creative metadata + lineage.
8. Physical work can be linked to that passport through a branded QR / URL.
9. MVP access is whitelist-only.
10. One real object is made, labeled, verified, listed, and moved through a real first-sale / transfer experiment.

Hackathon success is a convincing startup story, not the largest feature list.

---

# P0 — MUST SHIP BEFORE OCT 12

## RF-001 · ARTIST MIND / MEANING LAYER

**TYPE:** SYSTEM  
**STATUS:** APPROVED  
**TARGET:** HACKATHON P0

### Why
RUINFORM should not only transform physical matter; it should help the artist discover and package what the resulting work may mean.

### Product rule
RUINFORM proposes interpretation but never claims authorship over the artist's meaning. The artist may accept, edit, replace, or reject AI text. Grammar/punctuation suggestions require explicit approval before changing artist-authored copy.

### Metadata
- TITLE
- ARTIST THESIS
- SYMBOLIC READING
- MATERIAL METAPHOR
- SHORT STORY
- ARTIST STATEMENT
- VIEWER QUESTION
- TAGS / THEMES

### Creative authorship provenance
Each interpretive field should retain one origin state:
- `AI VISION`
- `ARTIST EDITED`
- `ARTIST VISION`
- `AI + ARTIST`

### Fact / interpretation boundary
Physical provenance is objective metadata. Artistic interpretation is subjective metadata. They must never be merged into one field or presented with the same authority.

### Pipeline
`IMAGINE → Concept Seed`  
`ACCEPTED RENDER → Artist Mind`  
`BRANCH / EVOLVE → inherit or evolve meaning DNA`  
`EXPLORE → short public story`  
`OBJECT PASSPORT → full creative metadata`

---

## RF-002 · FUTURE INTELLIGENCE / DIVERSITY

**TYPE:** SYSTEM  
**STATUS:** DONE  
**TARGET:** V1

Two visible Futures must feel like two genuinely different ideas, not two names for sibling geometry.

Implemented direction:
- distinct transformation families;
- distinct Concept Seeds;
- physical-operator truth over poetic wording;
- anti-sibling semantic logic;
- quality first, diversity second.

Keep regression coverage. Do not reopen unless new tests show drift.

---

## RF-003 · MULTI-MATERIAL ROLES

**TYPE:** SYSTEM  
**STATUS:** TESTING  
**TARGET:** HACKATHON P0

Every uploaded source must resolve to exactly one material decision:
- `HERO`
- `STRUCTURE`
- `CONNECTOR`
- `SURFACE`
- `SYMBOLIC`
- `UNUSED WITH REASON`

Do not force all source matter into every Future. Omission is a valid design decision, but it must be explicit.

Finish only the strict source-accounting / role-ledger layer before moving on.

---

## RF-004 · BRANCH / EVOLVE DNA

**TYPE:** SYSTEM  
**STATUS:** TESTING  
**TARGET:** HACKATHON P0

A descendant inherits and may evolve:
- FORM DNA
- MATERIAL DNA
- MEANING DNA

Rules:
- accepted parent Future is the design ancestor;
- old raw evidence remains provenance, not automatically active matter;
- new matter must causally change the descendant;
- parent identity remains recognizable unless explicitly overridden.

---

## RF-005 · OBJECT PASSPORT V0

**TYPE:** SYSTEM  
**STATUS:** APPROVED / NOT STARTED  
**TARGET:** HACKATHON P0

The Object Passport is the canonical record. Blockchain/NFT is an optional publication / ownership anchor, not the data model itself.

Passport V0 sections:
- OBJECT ID
- accepted render / object media
- creator
- created date
- Provenance: source matter + evidence
- Creative: Future + Artist Mind
- Lineage: parent / branches
- Making: simple Make Plan
- Verification state
- QR / canonical share URL
- ownership state

Create one persistent page per accepted object.

---

## RF-008 · VERIFICATION LITE

**TYPE:** TRUST SYSTEM  
**STATUS:** APPROVED / NOT STARTED  
**TARGET:** HACKATHON P0

Goal: credible anti-fake direction without pretending we can prove perfect physical authenticity.

### MVP flow
1. Passport issues a fresh camera challenge.
2. User captures through camera in-session; arbitrary gallery upload is not treated as proof.
3. Challenge requests a small set of dynamic views / details.
4. Challenge nonce + object ID + capture time bind the evidence to that verification attempt.
5. AI checks broad visual consistency against accepted object / required details.
6. Result is `VERIFIED-LITE / REVIEW / FAILED`.

### Later hardening
- anti-replay fingerprints
- motion / liveness challenges
- multiple required angles
- device attestation where available
- manual review path
- tamper-evident label / NFC where useful

---

## RF-009 · BRANDED QR + CANONICAL OBJECT URL

**TYPE:** IDENTITY  
**STATUS:** APPROVED / NOT STARTED  
**TARGET:** HACKATHON P0

Every Object Passport gets:
- branded RUINFORM QR
- canonical object URL
- human-readable short code
- creator-controlled country / city metadata where useful

QR resolves to the passport, not directly to NFT infrastructure.

---

## RF-010 · WHITELIST ACCESS

**TYPE:** ACCESS  
**STATUS:** APPROVED / NOT STARTED  
**TARGET:** HACKATHON P0

Initial launch is community-only / whitelist beta.

Need:
- invite / allowlist state
- user identity
- usage counters
- admin disable / revoke

Do not build full public billing before hackathon.

---

## RF-011 · COST / USAGE DASHBOARD V0

**TYPE:** FOUNDER OPS  
**STATUS:** APPROVED / NOT STARTED  
**TARGET:** HACKATHON P0

Founder needs immediate visibility into subsidy burn.

Minimum dashboard:
- users
- sessions
- READ calls
- Future generations
- renders
- estimated AI cost per user / project / day
- estimated media cost
- total daily spend
- spend trend chart
- cost per accepted object

Purpose: avoid subsidizing unlimited use blindly.

---

## RF-012 · ADMIN / PROJECT CRM V0

**TYPE:** FOUNDER OPS  
**STATUS:** APPROVED / NOT STARTED  
**TARGET:** P0 if simple, otherwise P1

Visual operational panel, not enterprise CRM.

Need:
- project / user list
- current stage
- stuck / failed sessions
- last activity
- cost estimate
- object count
- verification status
- visible warnings: what is broken / incomplete

Later: support notes, project improvement recommendations, cohort analytics.

---

## RF-013 · HACKATHON DOCUMENTATION / RUINFORM BIBLE V0

**TYPE:** DOCUMENTATION  
**STATUS:** APPROVED / NOT STARTED  
**TARGET:** HACKATHON P0

Documentation becomes the first RUINFORM Bible.

Need:
- problem
- unique insight
- product thesis
- principles / postulates
- architecture
- Object Passport model
- provenance vs interpretation
- verification model
- business model
- market
- GTM
- roadmap
- risks
- what was built during hackathon

Submission package also needs:
- product logo / graphic
- GitHub repo / access
- disclosure of relevant pre-existing work
- 2–3 minute presentation video
- <=3 minute product demo video
- GTM + demand validation narrative

---

## RF-014 · WALLET CONNECT / CRYPTO ANCHOR V0

**TYPE:** CRYPTO  
**STATUS:** APPROVED / RESEARCH FIRST  
**TARGET:** HACKATHON P0 only as a thin layer

Minimal useful crypto layer:
- connect wallet
- associate creator / owner wallet with passport
- optionally anchor one demo Object Passport hash / NFT reference onchain

Do not make blockchain the main UX.

---

## RF-015 · FIRST REAL OBJECT / FIRST SALE EXPERIMENT

**TYPE:** TRACTION EXPERIMENT  
**STATUS:** APPROVED / NOT STARTED  
**TARGET:** HACKATHON P0

Complete one real-world loop before submission:
- choose strongest RUINFORM object
- physically make it
- apply RUINFORM mark / burned label / plate / QR
- create Object Passport
- run Verification Lite
- photograph it
- create a listing
- make a real test purchase / transfer if feasible
- test packaging / shipping path
- record costs, friction, photos, failures

Potential Kazakhstan shipping route can be tested if useful operationally; it is not core architecture.

---

# P1 — ONLY IF P0 IS STABLE

## RF-016 · AI CHAT COPILOT

Contextual RUINFORM assistant that explains stages, helps improve concepts, interprets maker cues, and answers passport questions.

For hackathon, a lightweight contextual chat is enough. Autonomous actions are not required.

---

## RF-017 · EXPLORE V1

Upgrade Explore from image feed to object archive:
- image
- short story
- materials
- themes
- lineage
- creator
- passport link
- descendant branches

---

## RF-018 · PROJECT PERSISTENCE / REFRESH STABILITY

Critical refresh / restore bugs are P0 blockers. Broad persistence polish is P1.

Need eventually:
- refresh-safe candidate restore
- accepted render restore
- branch restore
- week-later resume
- durable project identity

---

## RF-019 · UX POLISH

Fix only high-friction issues before deadline:
- scroll traps
- overlapping panels
- ambiguous buttons
- broken images
- state mismatch
- error styling for non-errors

---

## RF-020 · QUALITY GATE STATES

Normalize to:
- PASS
- REVISE
- MUTATION

Quality Gate advises and protects the selected contract; it must not silently rewrite the artist's Future.

---

## RF-021 · COMMUNITY PASS / MEMBERSHIP NFT

Possible future community access credential after whitelist.

Do not block hackathon on it.

---

# PARKED — AFTER HACKATHON

## RF-006 · BUILD REALITY / VERIFIED ENGINEERING

**STATUS:** PARKED  
**TARGET:** V1.5 / EXPERIMENTAL

V1 keeps only:
`MAKE PLAN → simple maker cues → VERIFY`

Detailed measurement-driven engineering, fabrication gates and verified build planning are intentionally deferred.

---

## RF-007 · FUTURE LATENCY

**STATUS:** PARKED

Speed matters later, but creative quality and material intelligence come first.

---

## RF-022 · ARTIST TRAINING PANEL

Future creator tool where selected artists can contribute their own works / preferences to condition personal RUINFORM intelligence.

Not MVP.

Future questions:
- opt-in datasets
- artist ownership / consent
- provenance of style data
- adapter / model isolation
- compensation / licensing

---

## RF-023 · BYOK / USER-PAYS AI

Future personal account can attach its own API key or funded AI balance.

Research models:
1. BYOK: user pays provider directly.
2. RUINFORM credits: we meter and resell usage.
3. subscription + included credits.
4. hybrid: platform subscription + user-paid model usage.

Raw provider keys must be encrypted server-side and never returned to the client.

---

## RF-024 · BILLING / RUINFORM TAKE RATE

Research after cost-per-object and first transaction are known.

Possible revenue layers:
- creator subscription
- platform usage fee
- AI usage margin / credits
- marketplace take rate
- verification / passport issuance fee
- premium artist tools
- optional onchain mint / transfer fee

---

## RF-025 · CREATOR MARKETPLACE DISTRIBUTION

Initial channels to test:
- eBay
- Etsy / custom-art marketplaces
- direct RUINFORM Object Passport page

Goal is first demand evidence, not building a marketplace from scratch.

---

## RF-026 · SOCIAL CONTENT ENGINE

Build in public across relevant social channels.

Content loop:
`raw junk → AI thought → transformation → physical making → meaning → passport → sale`

Strongest format should show visible progress and human craft, not generic AI content.

---

## RF-027 · BUNKER AI CLONE / MCP-STYLE CREATOR AGENT

Future gamification / personalization layer: creator's AI presence inside the Bunker.

Start later with RUINFORM's house AI, then allow creator-specific agents / approved tool contexts.

Not a hackathon dependency.

---

## RF-028 · TRANSFERABLE PASSPORT / ANTI-COUNTERFEIT OWNERSHIP

Passport identity should survive resale.

Future transfer flow:
- current owner initiates transfer
- buyer wallet/account accepts
- ownership history is appended, never overwritten
- physical verification can be requested at transfer
- QR continues to resolve to the same object identity

NFT may become one ownership anchor, but Object Passport remains canonical product identity.

---

# SYSTEM CONNECTION MAP

`REAL MATTER`
→ `SEE / MATERIAL EYE`
→ `FUTURE INTELLIGENCE`
→ `MULTI-MATERIAL ROLES`
→ `RENDER`
→ `ARTIST MIND`
→ `OBJECT PASSPORT`
→ `LINEAGE`
→ `QR / URL`
→ `WALLET / OPTIONAL NFT`
→ `VERIFICATION`
→ `OWNERSHIP / TRANSFER`
→ `EXPLORE`
→ `SALE / LISTING`

`BRANCH / EVOLVE` loops from an accepted Future / Passport back into new matter while retaining `FORM + MATERIAL + MEANING DNA`.

`ADMIN / COST / CRM` observes the whole system.

`AI CHAT` helps the user across the system but is never authoritative over artist authorship.

---

# OCT 1–12 EXECUTION PLAN

## Oct 1–3 — freeze creative core
- finish RF-003 source accounting
- stabilize RF-004 Branch DNA
- implement RF-001 Artist Mind V0
- fix only blocking UX defects

Exit condition: one object reliably moves from matter → two strong Futures → accepted render → branch → meaning.

## Oct 4–6 — object identity + trust
- Object Passport V0
- branded QR / canonical URL
- Verification Lite camera challenge
- thin wallet association / crypto anchor if chosen

Exit condition: one accepted concept has a persistent passport and credible verification story.

## Oct 7–8 — founder operations + closed beta
- whitelist
- cost dashboard V0
- admin CRM V0
- persistence / refresh blockers

Exit condition: founder can see who is using RUINFORM, what broke, and approximately what it costs.

## Oct 9 — real object day
- make one object
- mark / QR it
- verify it
- photograph it
- list it
- test payment / purchase / transfer path as far as feasible

## Oct 10 — GTM + business model + Bible
- RUINFORM Bible V0
- business-model hypotheses
- distribution plan
- creator supply plan
- community plan
- submission draft

## Oct 11 — demo / pitch production
- record product demo
- record presentation video
- capture clean screenshots
- prepare repo / access
- rehearse exact 3-minute story

## Oct 12 — submission buffer only
- regression test
- fix only blockers
- submit early
- no new core features

---

# DO NOT BUILD BEFORE OCT 12

- full engineering Build Reality
- artist-model training platform
- full marketplace
- sophisticated subscription system
- production-grade anti-counterfeit guarantees
- full autonomous agent architecture
- creator BYOK platform
- complex NFT marketplace mechanics
- every social automation

These remain venture roadmap items, not hackathon MVP requirements.

---

# PRODUCT RULES

1. Real matter first.
2. AI proposes; artist owns final meaning.
3. Provenance facts never merge with interpretation.
4. Branches inherit DNA instead of restarting.
5. Object identity must outlive any individual render, NFT, owner, or marketplace listing.
6. Blockchain anchors identity / ownership; it does not define the product UX.
7. Verification states confidence and evidence; it never promises impossible certainty.
8. Closed beta and measured costs before public subsidized usage.
9. Every feature must strengthen the end-to-end object story or wait.
10. Hackathon success is a convincing startup, not the largest feature list.
