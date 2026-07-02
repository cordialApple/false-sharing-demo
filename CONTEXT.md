# CONTEXT.md

_Last updated: 2026-07-02 ~01:10 · branch: static-analysis-lab · session: built static-analysis heuristic platform (tier1+tier2), PR #1 open, /code-review mid-flight_

## 1. What changed this session
- Built `false-sharing-lab/static_analysis/`: full static false-sharing detection lab. Docs: `SOA.md` (state-of-the-art survey), `STRATEGY.md` (tier1 design), `TIER2_DESIGN.md` (tier2 design), `WORKPLAN.md` (phase tracker with all rounds + scores).
- `ir_analyzer.py` — tier1: pure-python textual LLVM-IR analyzer (H1/H2/H4; H2 handles both struct-GEP and array-of-struct GEP shapes). `analysis_agent.py` — LangGraph wrapper mirroring `agent/agent.py` (never run end-to-end; syntax-checked only).
- `tier2_pass/FalseSharingPass.cpp` — out-of-tree LLVM 18 new-PM plugin (H1–H5, DataLayout offsets, pthread_create call-graph closure, offset-based field resolution + GEP-type fallback). `tier2_analyzer.py` — CLI wrapper, same JSON contract as tier1. Builds via `tier2_pass/build.sh` (WSL or native Linux).
- `corpus/` — 18 labeled cases: `basic/` (10) + `advanced/` (8, real-world patterns: mutex+data, SPSC ring, lshaz stats array, nested fields, deceptive padding, per-thread malloc, alignas atomics, scalar global array). `labels.json` with `known_limitation` (expected miss) and `known_fp` (expected over-warn) semantics.
- `evaluate.py` — scoring harness: per-heuristic TP/FP/FN/GAP/KNOWN-FP, precision/recall; dual-mode Windows(WSL)/native-Linux; exit 0 iff no unexpected FP/FN. Results in `results/heuristic_scores_<analyzer>.md`.
- `.github/workflows/heuristic-eval.yml` — CI: builds pass on ubuntu-latest (clang-18/llvm-18-dev), runs harness as regression gate + tier1 smoke job. Both jobs GREEN on first run.
- Committed as `6a63f36` on branch `static-analysis-lab`, pushed; **PR #1 open**: https://github.com/cordialApple/false-sharing-demo/pull/1
- WSL Ubuntu got apt installs: clang, llvm, llvm-18-dev, cmake, g++.

## 2. Decisions made and why
- Two-tier analyzer design scored against one labeled corpus — the project goal is an EXPERIMENTATION PLATFORM for robust heuristics; analyzers are interchangeable via shared CLI contract (`<file.ll> --json`, tier1 JSON schema) registered in `evaluate.py` ANALYZERS dict.
- Tier1 = Route A (regex over `clang -S -emit-llvm -O0 -g` output, no llvm-dev); tier2 = real pass because it survives -O1 and covers atomics/globals. Both verified.
- `known_limitation` labels = expected misses (GAP, not FN); `known_fp` = expected over-warns; both keep CI green while recording the detection frontier honestly. Coarseness known: case-level, not per-analyzer/per-entry (altitude finding, see below).
- H4 requires thread-reachable context (corpus round 1 exposed FPs on single-threaded code). H2 excludes scalar-element arrays (`[8 x i64]`) — that's the H6 roadmap candidate.
- Caveman comment style (ALL-CAPS) mandatory in lab code per user; `/caveman` skill active for chat replies too.
- Worker pattern: Sonnet for research/corpus/CI, Opus for the C++ LLVM pass, orchestrator (Fable) steers + integrates. User wants this delegation pattern continued.
- Pushed to branch + PR (user chose over direct main push when asked).
- `{python}` placeholder → `sys.executable` in evaluate.py because Windows `python3` is a broken Store stub.

## 3. What was tested and how
- Full harness both tiers, 18 cases — `python evaluate.py` on Windows — exit 0; tier1: 5 TP/0 FP/0 FN/6 GAP; tier2: 7 TP/0 FP/0 FN/4 GAP; both precision & recall 1.00 on non-gap cases.
- Tier2 at -O1 — pass run on `ir/false_sharing_O1.ll` — still flags H2 on unpadded_counter_t (headline advantage).
- Native-Linux path — CI worker ran evaluate.py inside WSL bash natively — passed; then real CI on GitHub Actions run 28568433976 — both jobs pass (35s + 14s).
- `analysis_agent.py` — ast.parse only, NEVER run end-to-end (costs API tokens).
- /code-review (medium) on PR diff — IN FLIGHT: 8 finder agents launched; 3 of 8 returned (reuse: 6, efficiency: 6, altitude: 6 candidates); 5 finders still running (A line-scan, B removed-behavior, C cross-file, simplification, conventions). Verify phase NOT started, no findings report yet.

## 4. Files needing attention
- `false-sharing-lab/static_analysis/ir_analyzer.py` — review candidates: `_split_call_args` duplicates `split_type_list`; H4 GEP scan runs twice (steps 4A+4C); H2 regex shapes accumulating (needs general GEP matcher when H6 lands).
- `false-sharing-lab/static_analysis/evaluate.py` + `tier2_analyzer.py` + `analysis_agent.py` — three divergent win_to_wsl/WSL-dispatch implementations; analysis_agent.py hardcodes C: drive; find_opt re-probes WSL per invocation (54 spawns/run).
- `false-sharing-lab/static_analysis/tier2_pass/FalseSharingPass.cpp` — review candidates: H5 emits compound `"@A, @B"` struct field (can inflate TP matching); 5 separate instruction scans; O(g²) H5 pairing.
- `corpus/labels.json` — `known_limitation` is case-level; can't express per-entry or per-analyzer gaps (tier1's H3/H5 misses currently ride on labels shared with tier2).
- `.github/workflows/heuristic-eval.yml` — no apt cache; ~60–120s per run re-downloading LLVM.
- PR #1 — open, CI green, awaiting review/merge; review findings should be addressed on this branch.

## 5. Next step
Finish the in-flight /code-review: collect the 5 remaining finder results (or relaunch: angles A line-scan, B removed-behavior, C cross-file, simplification, conventions on `git diff main...HEAD`), dedup all candidates, run 1-vote verify agents, output ≤8 findings ranked by severity — then decide with the user which to fix on the PR branch.
