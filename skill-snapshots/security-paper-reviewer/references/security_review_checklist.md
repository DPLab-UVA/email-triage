# Security Paper Review Checklist

Use this as an audit list while reading and while writing the “Detailed Comments.”

## 1) Problem and scope
- State the exact problem and why it matters to security/privacy.
- Identify the target setting and non-goals (what is explicitly out of scope).
- Verify the paper’s claims match its setting (avoid over-claiming).

## 2) Threat model and assumptions (security papers)
- Identify the adversary goals, capabilities, and constraints.
- List the main assumptions (trust, side-channels, collusion, access levels, training data, deployment constraints).
- Check whether the evaluation matches the threat model (same capabilities and constraints).
- Check whether assumptions are stated early and clearly (not buried late in the paper).

## 3) Technical correctness
- For proofs/guarantees:
  - Confirm definitions are precise.
  - Confirm theorem statements match what is used later.
  - Flag missing steps, unstated assumptions, or unclear reductions.
- For systems/measurements:
  - Check for confounders and whether they are controlled.
  - Check if metrics support the claims (not just “better numbers,” but meaningful deltas).
  - Check for missing ablations (what part of the system matters).
- For ML-heavy work:
  - Ensure train/test splits are sound and leakage-free.
  - Check for cherry-picked datasets, labels, or prompts.
  - Check whether baselines are strong and tuned fairly.

## 4) Novelty and contribution
- Identify the closest prior work and what is actually new.
- Distinguish “new problem,” “new method,” and “better evaluation.”
- If the core idea is a known pattern, require strong evidence of novelty in this setting.

## 5) Evaluation rigor (common weak points)
- Scale: data sizes, number of users/devices/targets, realistic workloads.
- Baselines: strongest and most relevant baselines included?
- Robustness: variants of the attack/defense, parameter sensitivity, cross-domain tests.
- Negative results: where it fails and why (limitations section quality).
- Cost: latency/overhead, compute, storage, deployment friction.
- False positives/negatives: especially for detection/watermarking/IDS-style papers.
- Reproducibility: artifact/code, enough detail to re-run, clear hyperparameters.

## 6) Presentation quality
- Are key terms defined before use?
- Does the paper provide a clear “big picture” (problem → design → why it works → evaluation)?
- Are figures self-contained (labels/axes/legends), and do they help?
- Is related work positioned correctly (not hidden at the end if it is needed early)?

## 7) Ethics and broader impacts
- Human subjects: IRB/consent, participant risk, data retention.
- Sensitive datasets: PII handling, licensing/consent, safety.
- Dual use: could the method be weaponized; are mitigations discussed?
- Venue requirements: required “Ethics Considerations” section present?

## 8) Writing an actionable review
- Separate **major** issues (blockers) from **minor** issues (fixes).
- For each major issue:
  - Point to a concrete section/figure/claim.
  - Explain impact on correctness or evidence.
  - Ask for a specific fix (e.g., add experiment X, clarify assumption Y, compare to baseline Z).
- Keep the summary neutral and factual; put opinions in “Comments.”

