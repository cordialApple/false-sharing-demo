# CONTEXT.md

_Last updated: 2026-07-03 · branch: h6-round · session: H6 + FP fixes DONE, Huron recall 0.14 → 1.00; next = merge PR, then interprocedural H1 privacy + H7_

## 0. This session (H6 round — supersedes older sections below)
- PRs #1/#2/#3 all merged to main; grok mentions erased from all files (`2dcb610`, direct push authorized); local+remote branch cleanup done except `origin/static-analysis-lab` (remote delete permission denied — user deletes by hand).
- Branch `h6-round` off main: implemented in BOTH tiers: (1) H6 = variable-index store into free-standing shared scalar array (heap/global/arg base; skips stack-local, thread-private-heap, struct-embedded bases); (2) H2/H4 write requirement — store or atomic must flow through the var-index GEP chain (follows -O0 alloca-parked pointer reloads); (3) H1 intra-function instance privacy (malloc in thread fn, pointer never stored outside local slots / passed to pthread_create / returned).
- Tier1 subtleties learned: atomicrmw/cmpxchg count as writes for H2/H6 but NOT H1 (atomics are H3's, same split as tier2); H6 must reject bases that are themselves GEP results (ring->buf[i] FP).
- Corpus now 22 cases (+adv_tp_heap_scalar_array TP, +adv_tn_private_two_fields H1-privacy TN, +adv_tn_readonly_tid_array H2-write TN; global_scalar_array GAP→expected). `evaluate.py` exit 0: tier1 7TP/0FP/0FN/5GAP, tier2 9TP/0FP/0FN/3GAP.
- Huron re-run: **recall 7/7 (1.00) both tiers**, was 1/7. histogram + string_match are qualified hits (right object, imprecise mechanism). Round-2 section in `results/external_validation.md` has full table.
- Remaining known issues: H1 LocalCopies FP persists (malloc in SlaveStart, pointer passed to lu() — privacy is intra-function only; fix = interprocedural private-arg propagation); tier2 H6 FP on string_match getnextline (data-dependent index); H7 boundary heuristic would make the histogram hit mechanically correct.
- NEXT: open PR for h6-round (after /code-review), merge, then interprocedural H1 privacy + H7.

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
