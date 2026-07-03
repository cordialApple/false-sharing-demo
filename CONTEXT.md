# CONTEXT.md

_Last updated: 2026-07-02 ~19:45 · branch: external-validation · session: Huron external validation DONE; next = H6 + H7 heuristics from measured gaps_

## 0. This session (external validation — supersedes "next step" below)
- Branch `external-validation` (off static-analysis-lab). PR #1 untouched, still open.
- Cloned efeslab/huron (PLDI'19) in WSL `~/huron`; compiled 7 C test-suite programs to IR (`external/build_huron_ir.sh`, IR gitignored); ran BOTH tiers.
- Result: recall 1/7 (0.14) both tiers — the one hit is the canonical linear_regression `lreg_args` bug via H1. Full hit/miss/FP table + failure modes: `static_analysis/results/external_validation.md`.
- Measured gaps, priority order: (1) H6 scalar heap arrays = 4 of 6 misses (false.c, locked, lockless, lu_ncb); (2) new "H7" large-struct boundary (histogram: 3096B struct, size%64≠0); (3) string_match allocator-adjacency = out of static scope, documented.
- FP root causes found: H2 fires without any store (read-only POINT_T flagged HIGH); H1 has no instance-privacy (per-thread-malloc'd LocalCopies flagged).
- NEXT: implement H6 + H2 write-requirement + H1 privacy fix, re-run Huron suite as the honest benchmark, then H7 boundary heuristic.

## 1. What changed this session
- Built `false-sharing-lab/static_analysis/`: two-tier static false-sharing detection lab. tier1 = `ir_analyzer.py` (pure-Python textual IR analysis, H1/H2/H4); tier2 = `tier2_pass/FalseSharingPass.cpp` (out-of-tree LLVM 18 new-PM plugin, H1–H5, exact DataLayout, works at -O1) + `tier2_analyzer.py` wrapper (identical CLI/JSON contract).
- `corpus/` = 18 labeled cases (`basic/` 10, `advanced/` 8 from real-world patterns); `labels.json` with `known_limitation` (expected miss) + `known_fp` (expected over-warn) semantics. `evaluate.py` = per-heuristic TP/FP/FN/GAP/KNOWN-FP/ERR scoring harness, dual Windows(WSL)/native-Linux.
- CI `.github/workflows/heuristic-eval.yml`: builds pass on ubuntu-latest (clang-18/llvm-18-dev), harness exit code = regression gate + tier1 smoke job. Green.
- 8-angle /code-review ran; 8 confirmed bugs fixed in `ef8fb59` (ERROR verdicts uncounted→CI could lie green; `%struct.anon.N` regex miss; volatile stores missed; greedy JSON recovery crash; H1+H4 double-fire → suppression post-filter in BOTH tiers; C:-only WSL path; stale CI artifacts; label hygiene). Cleanups: deleted `_split_call_args` twin, H4 double scan, inline suppression guards.
- PR #1 (https://github.com/cordialApple/false-sharing-demo/pull/1): open, CI green, body rewritten PROFESSIONAL (user rejected all-caps) with honest framing: 1.00 scores are circular (corpus written alongside heuristics), external validation pending.
- WSL Ubuntu installed: clang, llvm, llvm-18-dev, cmake, g++.
- Memory files saved: code-review-before-pr, caveman-comments-mandate (comments only, PRs professional), corpus-bias-external-validation.

## 2. Decisions made and why
- Platform framing: analyzers are interchangeable via shared CLI contract (`<file.ll> --json`, tier1 JSON schema) registered in `evaluate.py` ANALYZERS dict — heuristics graduate on measured scores.
- In-house scores acknowledged as biased-by-construction; they gate regressions only. USER DIRECTIVE: find external datasets with known false-sharing instances to demonstrate non-bias. Candidates: Huron suite (github.com/efeslab/huron, PLDI'19), Phoenix programs used by SHERIFF/PREDATOR (linear_regression, word_count, histogram — canonical bugs), PARSEC/SPLASH-2, lshaz's Abseil/LLVM findings. Availability unverified.
- Caveman style: code comments yes; PR titles/bodies professional (user overrode their own CLAUDE.md). Commit messages: lean professional.
- Worker pattern (user-endorsed): Sonnet for research/corpus/CI/finders, Opus for LLVM C++ pass work, orchestrator steers/integrates/verifies. Always /code-review before opening a PR.
- Suppression policy is a single post-filter table per tier (`H2 > H1 > H4`), not scattered guards.
- `-O0 -g -std=c11 -pthread` for corpus IR; tier2's -O1 robustness is its headline advantage.

## 3. What was tested and how
- `python evaluate.py` (from `static_analysis/`, Windows): exit 0; tier1 5TP/0FP/0FN/6GAP, tier2 7TP/0FP/0FN/4GAP, ERR=0 — after all review fixes.
- CI runs 28568433976 and 28621897644 (post-fix): both jobs pass on GitHub Actions ubuntu-latest.
- Regex fixes verified empirically (clang 18 in WSL): `%struct.anon.0` now parses; `store volatile` now matches. Known non-regressions documented: tier1 can't see constexpr-GEP field writes on globals (pre-existing, same family as its H5 gap); nested-field attribution gap in both tiers (labeled, `adv_tp_nested_inner_fields`).
- `analysis_agent.py`: syntax-checked only, never run end-to-end (API cost).

## 4. Files needing attention
- PR #1 — awaiting human review/merge; all known work done on branch `static-analysis-lab`.
- `corpus/labels.json` — `known_limitation` is case-level, not per-analyzer/per-entry; will pinch when cases exercise multiple heuristics (schema change candidate).
- `evaluate.py` — external-dataset runs won't have labels in this format; validation flow needs a "findings report" mode (run analyzers, dump findings for human/dynamic confirmation) rather than TP/FP scoring, OR hand-labeled ground truth per external program.
- `tier2_pass/FalseSharingPass.cpp` — H5 emits compound `"@A, @B"` struct field (schema wart); 5 separate instruction scans (fine at corpus scale, slow on real programs — matters for external validation on big IR).
- Known perf warts if external programs are large: tier2_analyzer re-probes `opt` per invocation; evaluate.py spawns WSL per compile.
- Roadmap gaps (labeled in corpus): H6 scalar global arrays, nested-field attribution, opaque-call escape, fn-ptr thread entry.

## 5. Next step
External validation: research and fetch an independent dataset with documented false-sharing instances (start with the Huron benchmark suite at github.com/efeslab/huron and Phoenix's linear_regression — both have published ground truth), compile members to LLVM IR in WSL, run BOTH tiers, and produce an honest hit/miss/FP report per program (expect far below 1.00; label failure modes). Keep PR #1 as-is; do validation on a new branch.
