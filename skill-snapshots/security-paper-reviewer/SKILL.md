---
name: security-paper-reviewer
description: Draft conference-quality academic security/privacy paper reviews from PDFs (IEEE S and P, USENIX Security, CCS, NDSS style). Use when asked to review papers, write HotCRP-style reviews, or critique a paper's threat model, assumptions, methodology, evaluation, and ethics; includes a repeatable workflow and local scripts for PDF text extraction plus a structured review template.
---

# Security Paper Reviewer

## Overview

Produce structured, actionable reviews for security/privacy conference papers using a fast read-audit-write workflow and a consistent review format.

## Workflow

### 0) Confirm constraints (fast)

- **Template Discovery:** Check the paper filename to infer the venue (e.g., `sp` -> IEEE S&P, `ccs` -> CCS, `usenix` -> USENIX Security).
  - Search for a matching template (e.g., `sp_review_template.txt`).
  - **CRITICAL:** If a template for the venue is missing, **stop and ask the user to provide it**. Do not invent one.
  - Once provided, save it to `skills/security-paper-reviewer/templates/` for future use.
- If the user provides the actual HotCRP/offline review form, follow that form exactly rather than forcing the default template.
  - Preserve the venue’s section names, score scales, hidden/public fields, and any required label style (e.g., `S1/W1/C1/...`).
  - For CCS-style forms, map your internal analysis into the exact fields: summary, strengths, weaknesses, constructive comments, response questions, ethics, PC comments, expertise/confidence/merit, and open science.
- Ask which papers already have reviews and must be skipped.
- If example reviews exist, read them first to calibrate tone/formatting (labels, spacing, directness).

### 1) Inventory inputs
- List PDFs and any prewritten reviews in the workspace.
- Map review files to paper IDs / filenames (e.g., `review_216.txt` ↔ `paper216.pdf`).

### 2) Extract text (local, no external deps)
- Prefer `pdftotext` if available.
- Otherwise run:
  - `python3 "skills/security-paper-reviewer/scripts/extract_pdf_text.py" "paper.pdf" --out "paper.txt"`
- For a directory, run:
  - `python3 "skills/security-paper-reviewer/scripts/extract_pdfs_to_text.py" --dir "." --recursive`

### 3) Read efficiently (paper map + audit)
- Write a short “paper map” before drafting the review:
  - Problem and setting
  - Threat model (adversary, capabilities, assumptions)
  - Contributions (what is new vs. prior work)
  - Key mechanism (how it works, why it should work)
  - Claims (what is asserted/proved/measured)
  - Evaluation summary (datasets, baselines, metrics, scale)
  - Limitations and ethics (human subjects, sensitive data, dual-use)

#### Deep Dive Audit (Crucial for Top-Tier Venues)
- **Attacker Realism Check**:
  - *Training Data*: Does the attacker need victim data to train the attack model? (e.g., "We trained on the user's own data" = Within-Subject = Fatal Flaw in many threat models).
  - *Access*: Does the attack require unrealistic permissions or sampling rates (e.g., 500Hz sensor access in a web browser)?
- **Claim-Metric Alignment**:
  - *Verbs vs. Metrics*: If the paper claims "Reconstruction", does it measure pixel-wise similarity (MSE/SSIM) or just "Classification Accuracy" (40-class)? Classification $\neq$ Reconstruction.
  - *Causation vs. Correlation*: Is the signal truly from the claimed source (e.g., Brain EEG), or a confounder (e.g., Eye Muscle Movement)? Look for ablation studies (e.g., fixed-gaze control).
- **Occam's Razor & Baseline Check**:
  - *Necessity*: Is the complex method needed? Can a naive baseline (e.g., "Natural Hit vs. Miss" in cache attacks) achieve the same result?
  - *Missing Baseline*: Does the paper compare against the simplest possible attack?
- **Privacy Model Realism**:
  - For LDP/decentralized settings (especially graphs), clarify who the “client” is and how shared objects are handled (e.g., an undirected edge shared by two endpoints: who perturbs it, once or twice, and how symmetry/coordination is enforced).
- **DP / Privacy-Mechanism Audit**:
  - *Unit of Privacy*: Is the guarantee at user level, sample level, trajectory level, edge level, etc.? Does the paper overstate practical protection relative to the chosen unit?
  - *Adjacency Consistency*: Are all guarantees stated under the same adjacency notion? If not, does the paper improperly present separate guarantees under different adjacencies as one “full” or end-to-end guarantee?
  - *Composition / End-to-End Claim*: If multiple protected paths/components exist, does the paper actually prove a unified statement for the final release, or only separate guarantees on subcomponents/subdatasets?
  - *Private/Non-Private Training Paths*: If a released model is trained using any non-private component (e.g., non-private discriminator, teacher, scorer, retriever, simulator), check whether the privacy claim still follows. “The helper is not released” is not by itself sufficient.
  - *Aggregate vs Per-Sample Privatization*: If the method privatizes individual structured samples or per-record conditioning signals rather than aggregate statistics, ask whether the design is inherently near zero-sum: does utility survive only when privacy is weak?
  - *Sensitivity Story*: Is the sensitivity/clipping argument compatible with the actual object being privatized and the output dimensionality? Does the paper rely on a fragile or unrealistic bound?
  - *Attack Surface Match*: Does the protection mechanism actually cover the release path that matters (training leakage, generation-time input leakage, artifact release, auxiliary models, cached embeddings, etc.)?
- **Scope / Claim Audit**:
  - *Title vs Scope*: Does the title/readme frame the paper as a broad answer when the study only covers a few methods, datasets, or settings?
  - *Family-Level Conclusions*: If the paper compares “GAN vs VAE vs Diffusion” or similar families, did it study enough variants to support family-level conclusions, or only one implementation per family?
  - *Coverage*: For empirical “cost of X” / “systematic study” papers, ask whether omitted baselines or modern variants (e.g., additional architectures or non-DL families) materially weaken the generality of the claims.

- Audit with `references/security_review_checklist.md` when needed.

### 4) Draft the review (structured + actionable)
- Start from `assets/review_template.txt` and fill every section.
- Follow the user’s house style when provided:
  - Do not hard-wrap lines; keep each paragraph/point on one line.
  - Do not use bold formatting (e.g., `**text**`) in the review text; use plain text.
  - Leave a blank line between labeled points (e.g., T1/T2, S1/S2, W1/W2, C1/C2).
  - Leave a blank line after section headers like `Strengths:` and `Weaknesses:` before S1/W1.
  - Use labeled points instead of bullet lists for strengths/weaknesses/comments.
  - Avoid second-person (“you”, “authors”); prefer “The paper”, “The method”, “The definition/claim”.
  - Be direct; do not use “compliment sandwich” structure.
  - Write all math/symbols in LaTeX (e.g., `$\rho$`, `$\epsilon$`); avoid Unicode math characters.
  - LaTeX syntax: use single backslashes in commands (e.g., `\epsilon`, `\Pr`), not double-escaped forms like `\\epsilon` unless truly required by the surrounding format.
  - If the user wants a more human/less-polished style: prefer 2–3 short sentences for the summary; allow minor grammar imperfections; use parentheses for quick clarifications; avoid long “It proposes A, B, C” enumerations.
  - Keep Strengths/Opportunities points short (often <10–12 words); expand only in questions or detailed comments.
  - Keep it short: Paper Summary is usually 1–2 sentences; Strengths are 1–2 very short lines.
  - If the overall verdict is weak reject / reject, keep strengths especially sparse and factual. Do not pad them with generic praise.
  - If the overall verdict is weak reject / reject, keep constructive comments short too. Prefer short fixes over long explanatory paragraphs, and do not restate the full weakness in every comment.
  - “Short” does not mean “context-free.” Prefer a short lead sentence that states the point, followed by one sentence with the most important supporting context or prior-art anchor.
  - Avoid redundancy within lists: each Weakness (W1/W2/...) should cover a distinct aspect; merge overlapping points and keep the most concrete version.
  - If the form expects labels (`S1`, `W1`, `C1`, `R1`, `M1`, etc.), actually include them; do not forget label prefixes.
  - For fields like “Concerns to be addressed during revision/shepherding,” match the decision. If the verdict is weak reject / reject and there is no realistic minor revision path, say so directly instead of inventing shepherding items (e.g., “No clear path for revision and accept; better reject and resubmit.”).
  - Do not force content into “Constructive comments for author” if it would only repeat Weaknesses or response questions. If there is no new, non-redundant guidance, leaving that field blank is better than padding it.
- **Venue-Specific Rules:**
  - **IEEE S&P (SP):**
    - **Technical/Scientific/Presentation Comments:** Focus strictly on *negative* aspects (flaws, ambiguities, missing data). If a section is correct/good, say nothing or leave it empty. Do not offer praise.
  - **CCS / HotCRP forms:**
    - Prefer natural, concise prose over stiff template language, but keep arguments sharp.
    - Keep `Comments for PC` direct: decision, main blocker(s), and whether the issue is fixable in rebuttal.
    - Use the exact score numbers from the form instead of inventing alternate labels.
- Avoid redundancy across sections:
  - Keep Weaknesses high-level; they may reference earlier points (e.g., “see T1–T3”), but they do not have to—standalone weaknesses (e.g., efficiency, practicality, missing artifacts) are fine.
  - Use Detailed comments (C1, C2, ...) to expand the earlier points with concrete fixes; optionally include minor issues/typos there.
- Prefer high-signal brevity:
  - Technical Correctness points (T1, T2, ...) are not a fixed count: write them when there are clear technical issues; if confidence is low, phrase as clarification questions instead of asserting.
  - When working with a human reviewer, treat unconfirmed/uncertain technical critiques as candidates for discussion first; do not present them as definitive flaws.
  - If there are no major technical issues, include at least one positive technical correctness point (what seems sound / well-defined).
  - Put “small stuff” (typos/formatting/broken links/overflow/missing repo) under Minor; keep it terse and easy to copy/paste.
- Keep comments actionable:
  - State the issue.
  - Explain why it matters (security/validity/realism/reproducibility).
  - Propose a fix (clarification, missing experiment, stronger baseline, tighter claim).
- Ensure ratings match the narrative (avoid “can’t judge” + “no flaws”).

### 5) Final QA (before sending)
- Remove speculation; distinguish “missing detail” vs “incorrect.”
- Tie major criticisms to concrete requested changes.
- Check ethics requirements (explicit ethics section if required; IRB/consent for human subjects).
- Run one explicit `type / factor / scale` sweep before finalizing. Look for 1–3 concrete detail-level issues that can go into detailed comments or minor comments:
  - factor-of-two / adjacency-strength mistakes (e.g., add-remove vs replace-one, privacy-budget comparisons),
  - type/level confusions (user vs sample vs trajectory, family vs implementation, train vs test, public vs private),
  - unit / dimension / runtime / dataset-size mismatches,
  - code-paper mismatches in defaults, constants, or claimed settings.
- Sanity-check artifact claims: if the paper claims code/data in a repository (or includes a link), actually try to access the provided artifact link(s) when feasible.
  - Record what was claimed, what you attempted to open, and whether access worked.
  - If access failed, say why (e.g., `401`, broken link, web challenge, credentials unclear, placeholder only).
- Sanity-check “paper completeness” signals:
  - Literal placeholders left in text/tables (e.g., `[XX]%`, `[TODO]`, empty `[]` citations).
  - Extrapolated numbers presented like measured ones; if extrapolation is used, it should be explicitly labeled in captions/tables.
  - Duplicate references / missing bibliography cleanup that suggests rushed submission.
- Do a quick “Minor sweep” and list easy-to-fix issues under `Minor:` (labels like M1/M2 are optional; default to unlabeled short lines unless the venue template requires labels):
  - Spelling mistakes / obvious typos (e.g., “axillary” vs “auxiliary”).
  - Consistency issues like “etc...” (use either “etc.” or an ellipsis, not both).
  - Whitespace/punctuation glitches (e.g., “utility . Meanwhile,”).
  - PDF formatting issues visible in the PDF (reference overflow, figure/table overflow).
  - Ignore PDF-extraction artifacts (hyphenation at line breaks); if uncertain, verify in the PDF before calling it a typo.
  - Missing spaces / word concatenation is often a PDF-to-text extraction artifact; verify in the PDF before flagging it.
  - Minor formatting preference: for simple replacements, it is OK to write `"bad" -> "good"` (use ASCII `->`, not LaTeX arrows).
- Check that the decision is justified by the major points, not by minor presentation issues.

## Review output
- Use `assets/review_template.txt` by default.
- If the venue uses different headings (e.g., “Overall merit,” “Confidence,” “Ethics”), adapt headings but keep the same underlying content.
- For offline review forms, prefer filling the form file directly when the user provides one.

## Practical decision guidance (lightweight)
- Use **Reject** when the threat model/problem is unclear, core claims are unsupported, or evaluation cannot validate the claims (e.g., Classification masquerading as Reconstruction).
- Use **Weak Reject** when the idea is plausible but evidence is insufficient (missing key baselines/attacks/scale) or the method is overly heuristic without clear limits.
- Use **Weak Accept** when the contribution is solid and validated, with fixable gaps (clarity, missing ablation, additional realism checks).
- Use **Accept** when the paper is technically sound, clearly novel/significant, and the evaluation convincingly supports the claims.

## Notes from prior reviews

- For DP papers, judge more finely than “there is a proof” / “there is a mechanism.”
  - Check whether the guarantee matches the release path.
  - Check whether separate guarantees are being over-marketed as one full guarantee.
  - Check whether any non-private helper model breaks the claim.
  - Be skeptical of per-sample privatization schemes that give up aggregation and then claim a broadly useful privacy/utility tradeoff.
  - Do not confuse “component X uses DP-SGD” with “the released system is DP.” A DP update on one component is not enough if the released object is still trained through a non-private helper.
  - For claims involving helper models (e.g., GAN discriminator), write the critique in two steps: (1) state the condition under which the privacy claim would be valid, and (2) explain why the paper’s actual information flow does not satisfy that condition.
  - If a claim sounds wrong, do not stop at “prior work usually does the opposite.” Reconstruct the mechanism path (`data -> helper -> signal -> released model`) and explain exactly where the non-private dependency enters.
- Do not treat “many metrics,” “code release,” or “broad framing” as core contributions by default.
- When a paper claims broad architectural conclusions, ask whether it studied enough variants to justify conclusions about families rather than single implementations.
- Avoid empty praise such as “important problem” or “timely topic” unless the user explicitly wants that tone. Prefer concrete strengths tied to structure, method, evidence, or execution.
- For weak reject / reject reviews, concise beats exhaustive. Short, pointed lines usually read more like a real review than long balanced paragraphs.
- When making a critical point, a good default is: one short sentence with the judgment, one short sentence with the key reason or relevant prior-art context.
- Prior-art context should support the critique, not replace it. State the mechanism-level reason the claim fails or is unsupported; then use prior work only as an anchor.
- For DP critiques, make the information-flow argument explicit. If a released model depends on a non-private helper (e.g., discriminator, teacher, scorer, retriever), spell out what would have to be DP for the post-processing argument to go through, then state why the paper’s actual setup does or does not satisfy that condition.
- When criticizing a paper for lacking a takeaway, prefer constructive phrasing (e.g., “the paper would be more interesting / more compelling with a sharper takeaway”) over blunt dismissal.
- Do not use `Constructive comments for author` as a restatement of Weaknesses or response questions. Leave it blank if there is no new, useful guidance.
- If artifact links fail on the web but the user provides a downloaded archive, inspect the local artifact and update the review accordingly instead of preserving stale uncertainty.
- Before finalizing a weakness, ask: “Would this still be clear to an expert reader who has not seen my hidden reasoning?” If not, add the missing condition, mechanism, or scope qualifier directly into the sentence.
- Do not stop after the top-line verdict feels settled. Always do one last detail pass to hunt for `type / factor / scale` errors, because these often produce the most copy-pastable detailed comments.

## Bundled resources

- `scripts/extract_pdf_text.py`: Best-effort PDF text extraction (stdlib only).
- `scripts/extract_pdfs_to_text.py`: Batch extractor for a directory.
- `assets/review_template.txt`: Structured review skeleton matching common S&P-style headings.
- `references/security_review_checklist.md`: Detailed audit checklist and common pitfalls.
