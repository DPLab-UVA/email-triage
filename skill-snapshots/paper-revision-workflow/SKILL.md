---
name: paper-revision-workflow
description: Revise academic paper drafts, especially LaTeX conference papers, by aligning claims to evidence, restructuring introduction/methods/experiments/discussion, tightening prose, improving tables and figures, checking citations, and compiling to verify the final manuscript. Use when Codex is asked to rewrite, polish, strengthen, or prepare a paper for venues such as IEEE S&P, USENIX Security, CCS, NDSS, or ML conferences.
---

# Paper Revision Workflow

Use this skill to turn a rough paper draft into a cleaner, more defensible manuscript.
Optimize for claim discipline, structural coherence, artifact traceability, and final PDF quality.

## Core Principles

- Start from the paper's real evidence, not the story the draft wishes were true.
- Prefer fewer stronger claims over many weak or unsupported claims.
- Make the paper sound like a finished manuscript, not a lab notebook or project status update.
- Never leave author-facing drafting instructions inside the manuscript body. Phrases such as "the paper should", "this section should", "should be positioned as", "what will go here", or similar writer-to-self notes must be rewritten into reader-facing scientific claims or explicit draft-status statements.
- If a draft does not yet have real empirical results, do not write a fake `Results` section full of placeholders. Rename it to an honest reader-facing section such as `Evaluation Questions`, `Evaluation Protocol`, or `Planned Analyses`, and keep claims prospective rather than pretending the paper is already finished.
- Keep methods, experiments, tables, figures, and conclusion synchronized.
- Treat compilation and artifact verification as part of the writing workflow, not as an afterthought.
- For security/privacy and systems-adjacent venues, optimize simultaneously for novelty, practical or scientific impact, soundness, evaluation completeness, and reproducibility.
- Write so that a strong reviewer from a neighboring subfield can still see why the contribution matters; do not assume niche context will carry an incremental paper.
- Treat citation density as part of argument quality, not a cosmetic cleanup pass.
- When revising security/privacy or systems-adjacent papers, proactively seek a reviewer-style audit rather than waiting for the user to ask for one.
- When the user flags one local writing or layout issue, treat it as evidence of
  a possible manuscript-wide pattern. Fix the named spot, then proactively scan
  neighboring sections and similar constructs elsewhere in the paper instead of
  making a one-off patch.
- When one advisory or project-note phrasing pattern is fixed (for example
  repeated uses of "should", "current", "artifact", or similarly internal
  language), run a same-pattern search across the manuscript and clean the
  sibling instances that weaken the paper in the same way.

## Workflow

### 1. Inspect Before Editing

Read the main paper files first:
- the main `.tex` file
- the bibliography file
- included tables and figures that are referenced in the main text

If a code or results repository exists, inspect the experiment artifacts before changing empirical claims.
Prefer exported result files over manually copied numbers.
If figure data lives in a sibling repository or worktree, create a short
data-source manifest before revising captions or empirical claims.
If the manuscript or project docs reference remote run directories, shared-FS
paths, or sibling-worktree artifacts, verify that those exact paths still
exist before treating them as active evidence.
Do not assume a remembered artifact name is canonical.
Stale or renamed result paths are manuscript bugs, not merely ops issues, and
should be corrected before tightening claims around them.

Also inspect citation density early:
- scan the introduction and related-work sections for long uncited stretches
- mark sentences that assert importance, novelty, prevalence, realism, or prior-art gaps without support
- if the bibliography looks sparse or stale, plan a citation-refresh pass before polishing prose

If the user has recently edited the draft, inspect their local comments,
tracked-style notes, or diffs for pattern-level feedback.
Do not only resolve the exact line they marked.
Ask what broader category of problem the comment reveals: weak sectioning,
too much math, poor citation placement, short final lines, report-style tone,
or similar repeated issues.

### 2. Classify the Paper's True State

Decide which of these the draft actually is:
- a problem-formulation or framework paper
- an empirical benchmark paper
- a systems or mechanism paper
- a hybrid paper with one of those roles clearly primary

If the draft mixes incompatible roles, collapse it to the strongest honest version.
Do not let the introduction promise a finished benchmark if the code and results only support a framework paper.

### 3. Enforce Claim Discipline

For each major claim, check:
- what exact evidence supports it
- whether the evidence is direct or only suggestive
- whether the wording over-claims relative to the evidence

Rewrite aggressively when needed:
- replace vague superiority language with metric-specific statements
- distinguish formal guarantees from heuristic behavior
- distinguish empirical audits from proofs
- distinguish local operating-point wins from family-level conclusions

If a result is only preliminary, say so clearly.
If a paper-facing result depends on one dataset, one seed, or one task, scope the claim accordingly.
When the draft mixes benchmark-facing rows, bounded corroborative checks, and
still-running experiments, separate those categories explicitly.
Do not let an in-flight run or an infrastructure-validating bounded check drift
into the same prose role as a completed anchor row.

Also check the contribution bar itself:
- is the draft actually claiming a new mechanism, attack, defense, measurement finding, or benchmark lesson that changes how readers should think about the problem
- or is it mainly an implementation refinement, dataset swap, or local tweak dressed up as a broad contribution

If the advance is narrower than the introduction suggests, tighten the framing rather than trying to inflate novelty through prose.

### 4. Make the Threat Model Auditable

For security/privacy papers, the threat model must survive hostile reading.

Always make explicit:
- who the adversary is
- what the adversary knows
- what the adversary can do
- what the adversary cannot do
- why those limits are realistic for the deployment setting

Then check for consistency:
- do the attack or defense claims actually match the stated adversary
- are there hidden assumptions in proofs, experiments, or system design that the text forgot to state
- does the defended mechanism block the attack as defined, or only a weaker proxy
- could a realistic attacker bypass the proposed boundary with one unmodeled capability

If the paper's security story depends on a delicate assumption, surface it prominently instead of leaving it implicit.

### 5. Repair the Global Structure

Use a structure that matches the paper type.
For most conference papers, the stable order is:
1. Introduction
2. Related Work
3. Background / Threat Model / Release Semantics
4. Problem Setup and Design Goals
5. Method or Design Space
6. Experimental Methodology
7. Results
8. Discussion / Limitations / Ethics / Reproducibility
9. Conclusion

Prefer standard reader-facing section titles when they already communicate the
function clearly.
Avoid elaborate headings such as "First Empirical Study Design" when a simpler
title like "Evaluation" or "Experimental Setup" says the same thing more
directly.
In dataset or benchmark sections, prefer direct description over rhetorical
framing.
State what the dataset contains, why it is included, and what role it plays in
the paper; avoid ornate lead-ins such as "from a first-principles standpoint"
when a plain benchmark rationale is enough.
When multiple datasets or benchmark representations are involved, consider a
compact summary table that reports concrete properties such as source size,
number of static attributes, trajectory dimensionality, and the representation
actually used in the paper.

When the draft contains weak front-loaded tables, convert them to compact prose, lists, or a more formal mathematical setup unless the table truly helps comparison.
If the paper uses lists, standardize their indentation and spacing across the
manuscript rather than relying on class defaults.
For LaTeX conference papers, prefer a consistent `enumitem` policy such as
`leftmargin=*`, or route short contribution-style lists through a shared compact
environment so list layout does not drift from section to section.

### 6. Tighten the Introduction

The introduction should do four jobs:
- establish the problem and why it matters
- explain why existing adjacent literatures are insufficient
- state the paper's scoped contribution
- preview the paper's real findings without overselling

For top-tier security/privacy venues, the contribution statement must also answer:
- why this is not merely incremental
- why the security impact matters beyond one narrow benchmark or implementation setting
- why a reviewer outside the immediate subcommunity should care

In abstracts and introductions, prefer method-level and scientific framing over benchmark inventory.
Unless the dataset identity or scale is itself the contribution, avoid using the abstract to enumerate sample sizes, benchmark ladders, or repository logistics.
Move those details into the experimental methodology or results sections.

Add citations early.
Avoid pages of uncited motivation.
Do not treat citations as a final formatting step.
If the introduction or problem framing contains unsupported claims, proactively use [$bibtex-verify](/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/bibtex-verify/SKILL.md) to search for and verify stronger sources before tightening the prose.
Avoid meta language such as:
- "this revision"
- "this project"
- "the current paper should"
- "the repository now"
- "this section should"
- "what will go here"
- "should be positioned as"

Replace those with direct scientific statements.

### 7. Formalize the Problem and Methods

When possible, rewrite informal method descriptions into a shared mathematical frame.
Prefer one common notation across method families so the reader can compare them directly.

Useful pattern:
- define the data unit
- define the release mechanism
- define the design goals or loss views
- define each method family as a different factorization or estimator of the same joint object

When simplifying math, do not leave the surrounding prose half-updated.
If a formal block is reduced or removed, rewrite the nearby notation,
terminology, and design-goal prose so the reader still knows what the symbols
mean and why they are being used.
Define core terms before relying on them repeatedly; for example, if the paper
uses phrases such as "method family" or "claim level" as organizing concepts,
introduce those terms explicitly before saying "each family" or "each level."
Avoid internal drafting phrases such as "paper-facing examples." Replace them
with direct reader-facing prose and, when examples are named, attach citations
to the examples rather than leaving them as uncited placeholders.

If one method family is the leading one empirically, separate:
- the general family definition
- the leading concrete instantiation
- the evidence-backed operating points

If a method family decomposes naturally into separable components, do not
default to one generic model class for every component.
State clearly which subproblem each component solves, and instantiate each
component with the strongest method actually appropriate for that subproblem.
In integrated-data papers, this often means that a serious modular baseline
should combine a strong tabular model, a strong trajectory model, and an
explicit coupling stage, rather than reusing a generic tabular VAE or diffusion
model as a stand-in for the whole family.

Do not let auxiliary references masquerade as canonical family representatives.
If a flattening baseline, tabular-only model, or generic neural baseline is
kept mainly to show what is lost under a weaker inductive bias, label it as an
auxiliary baseline or auxiliary reference rather than implying that it is the
best available instantiation of that method family.

When a paper first introduces a broad taxonomy and then zooms in on one family,
make that narrowing explicit.
Do not let later sections read as if the other families disappeared by accident.
State clearly whether the focus shifts because one family is empirically
leading, more concretely implemented, more amenable to mechanism-level
analysis, or otherwise the only family that currently supports the deeper
discussion.

If a subsection is trying to do multiple rhetorical jobs at once, split them.
Common failure modes include mixing:
- what is implemented
- what is missing
- what the paper can honestly claim
- what the next priorities are
When that happens, rewrite the section into explicit paragraphs or smaller
subsections so the reader never has to infer the section's function.

If a paper uses internal family labels such as S1/S2/S3, style them
consistently and conservatively.
Prefer one low-key house style over decorative formatting, and use the same
label treatment in headings, captions, and prose so the manuscript does not
switch between tagged and untagged family references.

When a methods section serves both as a scientific taxonomy and as a report on
the current codebase, separate those layers explicitly.
Explain the general framework, general implementation or traceability
requirements, and general privacy-accounting obligations before opening a
distinct subsection that says what is currently implemented and which family or
line currently leads.

For DP- or privacy-centered papers, add a second pass that checks whether the
formal setup matches the release semantics the paper actually studies.
In particular:
- spell out ``differential privacy (DP)'' the first time it is formally
  introduced in the paper or in a major literature subsection, and support that
  introduction with a canonical citation
- by default, treat ``DP'' as the paper's main model and only bring in local-DP,
  shuffle-DP, or other variants when the contrast is scientifically relevant
- do not mix incompatible privacy models or trust assumptions in one related-work
  line without explicitly saying why they belong together
- prefer plain-language explanation before equations when defining the protected
  unit, release mechanism, adjacency relation, and release semantics
- make the adjacency notion match the claimed release semantics; for user-level
  releases, check carefully whether add/remove adjacency is the natural choice
  rather than replace-one adjacency
- after simplifying notation, verify that mechanism signatures, adjacency
  definitions, accountant language, and later method equations still agree
- if the paper is about what can be claimed under a given privacy notion, say in
  prose why weaker units such as row-level or time-step-level protection would
  understate the risk

### 8. Rebuild the Experimental Narrative

Make the experimental section answer a small number of explicit research questions.
Typical pattern:
- main benchmark
- ablation
- downstream utility
- privacy evidence
- stability or uncertainty
- second dataset or transfer

Within each subsection:
- introduce what the table or figure shows
- state the main takeaway
- explain the failure mode or tradeoff
- connect it back to the paper's main claim

Do not let tables and figures float without interpretation.

For security/privacy and systems-adjacent papers, also audit the experimental design itself:
- does the dataset or environment coverage match the paper's claimed deployment scope
- are the baselines both strong and fair
- do the reported metrics actually measure the claimed security or privacy objective, rather than only task accuracy, speed, or convenience
- are ablations isolating the claimed mechanism rather than mixing several changes at once
- would an artifact reviewer or skeptical reader be able to reproduce the headline result from exported files and stated settings
- if the paper cites corroborative bridge evidence from a different backbone,
  public-control setting, or bounded-data path, is that evidence clearly
  labeled as corroborative rather than silently promoted into the main
  benchmark package

### 9. Treat Tables and Figures as Arguments

For every table and figure:
- verify the asset exists
- verify the caption matches the actual content
- verify the surrounding prose matches the asset
- verify highlighted rows or notes still reflect the latest incumbent
- inspect the rendered PDF page, not just the source, to catch density,
  overlap, weak hierarchy, or “lab notebook” looking layouts
- when one figure is flagged as weak, proactively audit neighboring figures
  for the same failure mode instead of only patching the one that was named
- when one paragraph, caption, or subsection is flagged for awkward line
  endings, weak tone, or unnecessary structure, audit sibling paragraphs,
  captions, or subsections for the same pattern before stopping

Improve presentation when needed:
- convert weak overview tables into prose or lists
- prefer a concise caption or a formal table note over tiny “Reading guide”
  microtext under the table
- use consistent labels, captions, and visual language
- highlight the scientifically important row, not just the numerically smallest entry
- prefer scripts that regenerate figure assets directly from exported result
  files instead of hand-editing plot values
- keep in-figure titles neutral and descriptive; put the stronger conclusion in
  the caption or surrounding prose unless the title itself must carry a formal claim
- avoid lab-notebook experiment jargon such as `sweep` when direct language is
  clearer; prefer phrases such as `evaluation at different sample sizes`,
  `across different noise-scale values`, or `study over formal privacy
  parameters`
- similarly, avoid internal-progress words such as `pilot`, `smoke`,
  `incumbent`, or `headline` when a more reader-facing alternative is clearer;
  prefer `small-sample diagnostic`, `end-to-end check`, `best verified
  configuration`, `primary metric`, or `main result`, unless the original term
  has a genuine technical meaning in context
- when a paper uses a compact taxonomy such as `S1/S2/S3`, refer to the tagged
  categories directly instead of writing awkward hybrids like `family S1` unless
  the sentence truly needs the extra noun
- subsection and paragraph titles should answer a concrete question directly;
  prefer titles like `Why S2 fits this problem best` over vague or rhetorical
  headings such as `Why S2 is the main scientific bet`
- if a paragraph is mainly an internal roadmap (`what to prioritize next`,
  `next loop`, `future implementation order`), delete it or fold only the
  scientifically necessary part into nearby prose; do not keep project-planning
  text as a standalone scientific point
- if you add an appendix proof for a privacy mechanism, attach it only to a
  mechanism whose adjacency relation, contribution bounding, released objects,
  and accountant are already explicit and traceable; state just as explicitly
  what the proof does \emph{not} cover, especially if the paper's empirically
  leading method is still heuristic
- when justifying why one method class is the main line of development, ground
  the claim in three layers when possible: problem structure, accounting or
  interpretability advantages, and current empirical evidence; make explicit
  whether the claim is local to the present problem setting or meant as a
  broader statement
- if the experiments are not yet strong enough to support the method-choice
  claim, downgrade the wording to a conjecture or structural hypothesis rather
  than leaning on thin empirical evidence
- when using abstract labels such as `static` and `dynamic`, tie them back to
  the paper's actual notation and objects (for example, `a \in \mathcal A` and
  `s \in \mathcal S`) so the reader knows exactly what is being contrasted
- if a method family has more than one natural orientation or factorization
  (for example `A \to S` versus `S \to A`), state that explicitly and explain
  what determines the preferred direction
- when no single family is yet empirically justified as the clear main line,
  compare the families through a common lens such as structural assumptions,
  training burden, data requirement, and accounting difficulty instead of
  forcing a winner
- avoid standalone sections that mainly document obvious workflow mechanics
  unless they materially affect the scientific claim; if traceability matters,
  fold it into the accounting, controls, or reproducibility discussion instead
- avoid tautological or confounded tradeoff plots; if one plotted axis already
  contains the other metric, separate the metrics or redesign the figure
- for small diagnostic comparisons, prefer the simplest readable form
  (grouped bars, dot plots, or a clean paired comparison) rather than a clever
  visualization that needs text to explain why it was drawn that way
- choose paired-point or slope plots when the core comparison is a change
  between matched methods on the same quantity; do not force that style onto
  small diagnostic figures if grouped bars or simple dots are clearer
- avoid one-row memo tables; either expand them into outcome tables with an
  interpretation column or convert them to prose
- when a summary table carries part of the argument, prefer a formal note
  block under the table rather than hiding the reading guide in distant prose
- once a table starts carrying a `reading`, `supported reading`, or similarly
  argumentative interpretation column, strongly consider moving that
  interpretation back into the prose and shrinking the table to factual
  outcome columns only
- replace code-like dumps of feature names, config ids, or variable labels with
  reader-facing phrasing or a compact summary table whenever the raw strings are
  hurting page quality
- strip internal run labels such as `pe_last`, `filter/inter`, or similarly
  code-facing experiment ids from the final manuscript unless the identifier
  itself is scientifically necessary; prefer reader-facing descriptions in
  tables, figure labels, and captions

When there is a difference between a local optimum and a shared operating point, say both explicitly.

### 10. Clean Related Work

Organize related work by scientific function, not by a loose list of papers.
For example:
- DP tabular synthesis
- DP trajectory synthesis
- longitudinal synthetic health data
- privacy auditing and synthetic-data evaluation

For each subsection, state:
- what this literature solved
- what it did not solve for the current paper

Add missing citations where claims need support.
Use verified sources and real bibliographic entries.
Do not rely on a few canonical old citations when the field has clearly evolved.
When refreshing citations, proactively use [$bibtex-verify](/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/bibtex-verify/SKILL.md) to:
- verify that a cited paper is real and correctly represented
- add missing foundational or recent papers by DOI/title
- clean duplicate or stale BibTeX entries
- prefer authoritative sources such as DOI, DBLP, OpenAlex, Crossref, or Semantic Scholar over hand-written placeholders

Do not leave a related-work subsection at the level of "high-level split plus one or two old examples" when the area clearly has stronger internal structure.
Prefer method-family or lineage-based organization over shallow labels such as "statistical vs neural" when the real scientific story is more specific.
Keep incompatible privacy or trust models separate unless the contrast is explicit and important.
For example, do not casually mix centralized DP and local DP exemplars in one line of argument without saying why both belong.
If the only function of a related-work subsection is to say "no prior work solves our exact problem," strongly consider collapsing it into one closing paragraph instead of keeping a standalone heading.

### 11. Write Discussion and Limitations Like a Mature Paper

Discussion should interpret the evidence, not recap the results section line by line.
Focus on:
- why the leading methods win
- what the privacy audits do and do not mean
- what broader benchmarking lessons already follow

Avoid reviewer-facing or venue-facing throat-clearing when a direct scientific sentence will do.
For example, replace openings such as "security reviewers are usually not satisfied..." with a direct statement about what distinction or evidence boundary actually matters.

Limitations should be concrete:
- missing accountant
- weak comparator coverage
- limited task matrix
- missing uncertainty on some multi-setting evaluations
- dataset external-validity gaps
- threat-model assumptions that remain fragile
- deployment assumptions that are reasonable but not yet validated
- artifact or reproducibility gaps that block a stronger claim

Avoid motivational filler.
Also remove project-management or repository-status language from mature-paper sections.
Section titles and prose should sound like scientific interpretation, not internal planning labels such as "submission-ready", "repository mapping", or "paper-facing artifacts."

### 12. Compile and Verify

Always compile after meaningful edits.
For LaTeX papers, prefer `latexmk -pdf -bibtex`.

Check:
- undefined references
- undefined citations
- missing files
- obviously broken figures or tables
- severe overfull boxes
- clickable internal references and citations in the rendered PDF; for LaTeX,
  prefer enabling this with `hyperref` unless the venue template already
  handles links

Minor float-layout `Underfull \vbox` warnings are usually acceptable if the PDF looks correct.

### 13. Final Clean Pass

Before stopping, do one last pass for:
- section-title consistency
- caption style consistency
- introduction/conclusion alignment
- repeated phrases or meta commentary
- benchmark names, metric names, and notation consistency
- whether the paper would still read coherently to a reviewer who only skimmed
  the figures, tables, and captions
- obviously awkward paragraph endings, especially when the final line is much
  shorter than the lines above it; if a last line is roughly under one-third of
  the normal line width, try to rephrase or tighten the paragraph unless doing
  so would make the prose worse
- sections or subsections that can be collapsed because they only restate
  obvious setup, create visual fragmentation, or carry too little scientific
  weight to justify a standalone heading

If the user is likely to review in Overleaf or another mirror directory, sync the updated assets and main paper files there as well.

### 14. Review-Driven Gap Check

For security/privacy or systems-adjacent drafts, do one short internal
review-style pass after the prose and figures are cleaned up.

- identify the likely top 2--4 reviewer objections
- distinguish presentation fixes from true evidence gaps
- turn evidence gaps into concrete next experiments, not vague future work
- if another local review skill exists, use it as a second-pass audit rather
  than guessing what a top-tier reviewer will focus on

For security/privacy papers, proactively invoke [$security-paper-reviewer](/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/security-paper-reviewer/SKILL.md) when available after the draft is structurally coherent.
Use that pass to stress-test:
- the threat model
- the contribution bar
- claim-evidence alignment
- evaluation completeness
- artifact and reproducibility claims

Do not wait for the user to request a review if the paper is clearly headed for a security/privacy venue; treat the review-style audit as part of manuscript hardening.

Use a generic high-bar checklist when doing this pass:
- novelty: is the contribution genuinely non-incremental at the paper's claimed scope
- impact: does the paper change what practitioners, defenders, attackers, or researchers should do or believe
- soundness: are the threat model, assumptions, and proofs or arguments internally consistent
- evaluation: are the datasets, environments, baselines, and metrics strong enough for the claim
- reproducibility: could another team audit the artifact trail and recover the main result without guesswork

## Writing Heuristics That Usually Help

- Replace "X wins" with metric-specific evidence.
- Replace "formal privacy" with the exact guarantee and mechanism, or downgrade the wording.
- Replace "best method" with "leading implemented method" when comparator coverage is incomplete.
- Replace "time smoothing wins" with the exact structural lesson the ablation supports.
- Replace giant summary tables with prose unless the comparison truly requires a table.
- Replace "realistic attacker" with the exact attacker capabilities and limits.
- Replace "strong evaluation" with the specific evidence that makes it strong: broader coverage, fairer baselines, security-aligned metrics, or better uncertainty reporting.
- Replace benchmark-centered abstracts with mechanism-centered abstracts unless the benchmark itself is the contribution.
- Replace repository or artifact-management language with reader-facing scientific language such as release semantics, evaluation traceability, or exported run records.
- Replace paragraph endings that strand one or two words on the final line when a
  small rephrase can eliminate the visual distraction.

## Output Expectations

When using this skill, aim to leave behind:
- a manuscript that compiles
- prose that matches the real evidence
- synchronized tables and figures
- citations that support the introduction, related work, and core claims
- a threat model and contribution statement that could survive skeptical review
- a concise summary of what changed, what remains weak, and what the user should review next
