# Static Analysis Work Plan — Compiler-Based (LLVM) False Sharing Detection

Extends the false-sharing-lab: the benchmark **measures** false sharing at runtime;
this module **predicts** it at compile time from LLVM IR, closing the loop
(static prediction → dynamic confirmation via the existing benchmark).

## Orchestration (model assignments, adjusted by difficulty)

| Phase | Task | Worker | Rationale | Status |
|---|---|---|---|---|
| 1. SOA | Survey compiler-based false-sharing detection (SHERIFF, PREDATOR, LASER, perf c2c, LLVM pass routes) | Sonnet | Web research: breadth over depth, token-cheap | DONE |
| 2. Install assessment | Probe WSL toolchain, install clang/llvm via apt | Orchestrator (inline) | Trivial shell work, no agent needed | DONE (clang 18.1.3) |
| 3. Strategy synthesis | Merge SOA + environment constraints into STRATEGY.md | Orchestrator (Fable, opus-tier) | Steering/design decisions stay with the strongest model | DONE |
| 4. POC implementation | Python IR analyzer + LangGraph agent wrapper mirroring agent.py | Sonnet (tight spec) | Well-specified codegen; spec quality substitutes for model tier | **DONE** — Makefile, ir_analyzer.py, analysis_agent.py created; verified: unpadded_counter_t → HIGH/H2, padded_counter_t → clean |
| 5. Verification | Run POC against false_sharing.c; expect unpadded flagged, padded clean | Orchestrator (inline) | Ground-truth check on the known benchmark | **DONE** — independent re-run from clean IR: H2/HIGH on unpadded_counter_t (worker_unpadded), padded_counter_t clean; JSON mode verified |

## Tier 2 — heuristic experimentation platform (2026-07-01)

Project reframed: this lab develops **robust static detection heuristics
empirically**. Two analyzers (Tier 1 regex, Tier 2 LLVM pass) are scored
against a labeled corpus; heuristics graduate on measured precision/recall.
Design: TIER2_DESIGN.md.

| Phase | Task | Worker | Status |
|---|---|---|---|
| 6. Toolchain | llvm-18-dev, cmake, g++ in WSL | Orchestrator (inline) | DONE (LLVM 18.1.3, CMake 3.28.3, g++ 13.3) |
| 7. Tier-2 design | Pass architecture, heuristic set H1–H5, shared JSON contract | Orchestrator (Fable) | DONE — TIER2_DESIGN.md |
| 8. Labeled corpus + eval harness | corpus/*.c with labels.json; evaluate.py scoring analyzers (TP/FP/FN, precision/recall) | Sonnet | DONE — 10 cases, honest scoring |
| 9. Tier-2 LLVM pass | tier2_pass/ (new-PM plugin, DataLayout, call-graph, H1–H5) + tier2_analyzer.py wrapper | **Opus** (hardest task) | DONE — verified at -O0 AND -O1 |
| 10. Integration & scoring | Register tier2 in evaluate.py, score both tiers, honest gap report | Orchestrator | DONE — see scores below |

### Corpus-driven fixes (the platform working as intended)

Round-1 scoring exposed real defects; fixed and re-scored:
- **H4 lacked thread guard** (both tiers): fired on single-threaded code. FP on
  tn_single_thread + edge_fnptr_entry. Fix: H4 requires thread-reachable context.
- **Tier-2 H1/H3 dropped accesses via opaque `void *arg`**: offset-based base
  resolution failed on thread-parameter pointers. Fix: fall back to GEP
  source-element-type attribution when base unresolvable.

### Final scores (results/heuristic_scores_*.md)

| Analyzer | TP | FP | FN | GAP | Precision | Recall |
|---|---|---|---|---|---|---|
| tier1 (regex, -O0 only) | 2 | 0 | 2 | 1 | 1.00 | 0.50 |
| tier2 (LLVM pass, -O0/-O1) | 4 | 0 | 0 | 1 | 1.00 | **1.00** |

tier1 FNs = H3 (atomics) + H5 (globals), unimplemented there by design.
Shared GAP = edge_fnptr_entry: runtime function-pointer thread entry is
statically unresolvable — fundamental limitation, documented, not penalized.

## Round 3 — corpus growth + CI/CD (2026-07-02)

| Phase | Task | Worker | Status |
|---|---|---|---|
| 11. Advanced corpus | corpus/ reorg (basic/ + advanced/); 8 hard cases from real-world patterns (mutex+data, SPSC ring, lshaz stats array, nested fields, deceptive padding, per-thread malloc, alignas atomics, scalar global array) | Sonnet | DONE — offsetof-verified layouts |
| 12. CI/CD + portability | evaluate.py/tier2_analyzer.py native-Linux dual-mode; known_fp scoring; .github/workflows/heuristic-eval.yml (build pass, run harness, artifact upload; tier1 smoke job) | Sonnet | DONE — end-to-end verified in WSL as Linux proxy |
| 13. H2 shape fix | Corpus exposed mislabeled gap: global fixed arrays emit ArrayType-source GEPs ('[4 x %struct.X], ptr @g, i64 0, i64 %var'); H2 only matched StructType-source (malloc shape). Fixed both tiers; scalar-element arrays excluded (H6 territory) | Tier1: Orchestrator; Tier2: Opus | DONE — stats_array now TP both tiers |

### Round-3 scores (18 cases, exit 0)

| Analyzer | TP | FP | FN | GAP | Precision | Recall |
|---|---|---|---|---|---|---|
| tier1 | 5 | 0 | 0 | 6 | 1.00 | 1.00 |
| tier2 | 7 | 0 | 0 | 4 | 1.00 | 1.00 |

Open gaps (= heuristic roadmap, all labeled in corpus/labels.json):
- **H6 candidate** (both tiers): variable-index store into global SCALAR array (`counters[tid]++`, no struct).
- **Nested-field attribution** (both): `o->in.b` attributed to inner struct; never co-resident with outer fields in H1's view.
- **Opaque-call escape** (both): `pthread_mutex_lock(&p->m)` hides the mutex field write; H1 sees one field.
- **Function-pointer thread entry** (both): fundamental static limit.
- **H3/H5 in tier1**: atomics + globals unimplemented in the regex tier (tier2 covers).

## Architecture (mirrors c_benchmark + agent workflow)

```
static_analysis/
  WORKPLAN.md            <- this file
  SOA.md                 <- phase 1 output (state of the art survey)
  STRATEGY.md            <- phase 3 output (chosen detection strategy)
  ir_analyzer.py         <- core: parses clang -emit-llvm IR, applies heuristics
  analysis_agent.py      <- LangGraph agent: emit_ir -> analyze_ir -> write_report
  Makefile               <- emit .ll IR from c_benchmark sources via WSL clang
```

## Detection tiers (effort-ranked)

- **Tier 1 (POC, this repo):** textual analysis of `clang -S -emit-llvm` output in
  Python. No LLVM dev libraries needed. Heuristics over struct layouts + GEP
  access patterns + pthread_create thread-entry discovery.
- **Tier 2 (future):** out-of-tree LLVM pass (`opt -load-pass-plugin`) with real
  alias/DataLayout queries. Requires llvm-dev + cmake in WSL.
- **Tier 3 (future):** clang-tidy checker for editor-time feedback.

## Comment style

Code comments follow the requested /caveman convention (ALL-CAPS primitive
grammar). Note: no /caveman skill is installed in this environment, so the
style is emulated.
