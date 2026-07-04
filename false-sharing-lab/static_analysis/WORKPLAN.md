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

## Round 4 — H6 + Huron-driven FP fixes (2026-07-03)

| Phase | Task | Worker | Status |
|---|---|---|---|
| 14. H6 both tiers | Variable-index store into free-standing shared scalar array (heap ptr, fixed global, arg base; skip stack-local, thread-private-heap, struct-embedded) | Orchestrator (Fable) | DONE |
| 15. H2/H4 write requirement | Fire only if a store/atomic flows through the variable-index GEP chain (incl. -O0 alloca-parked pointer reloads) | Orchestrator (Fable) | DONE |
| 16. H1 instance privacy | Skip struct instances malloc'd in the thread fn whose pointer never escapes to another thread (intra-function) | Orchestrator (Fable) | DONE |
| 17. Corpus regression cases | adv_tp_heap_scalar_array (H6 TP), adv_tn_private_two_fields (H1 privacy TN), adv_tn_readonly_tid_array (H2 write-req TN); adv_tp_global_scalar_array flipped GAP→expected | Orchestrator | DONE |
| 18. Huron re-run | Honest benchmark re-run | Orchestrator | DONE — recall 0.14 → **1.00** (7/7, 2 qualified), see results/external_validation.md round 2 |

### Round-4 scores (22 cases, exit 0)

| Analyzer | TP | FP | FN | GAP | Precision | Recall |
|---|---|---|---|---|---|---|
| tier1 | 7 | 0 | 0 | 5 | 1.00 | 1.00 |
| tier2 | 9 | 0 | 0 | 3 | 1.00 | 1.00 |

Remaining roadmap: interprocedural H1 privacy (lu_ncb LocalCopies FP),
H7 large-struct boundary mechanism (histogram flagged via H6 but with
imprecise rationale), nested-field attribution, opaque-call escape,
fn-ptr thread entry, tier1 H3/H5.

## Round 5 — Gemini roadmap adoption: H7 + sync modeling + topology (2026-07-03)

Source: Gemini's implementation_plan.md (7-phase frontier roadmap). Adopted
phases 1, 4, 6a; deferred 2 (allocator modeling), 3 (SCEV symbolic offsets),
5 (interprocedural/LTO), 6b (prefetcher), 7 (auto-padder) as future rounds.

| Phase | Task | Status |
|---|---|---|
| 19. H7 both tiers | pthread_create arg = &args[i] (var-index GEP), sizeof >= 64, sizeof % 64 != 0, align < 64 -> boundary-straddle warning; suppresses H4 | DONE |
| 20. Lock-call write modeling | pthread mutex/spin/rwlock lock/unlock counts as a write to the lock-word field (H1 evidence + H2/H6 write requirement) | DONE — closes adv_tp_mutex_data_same_line GAP both tiers |
| 21. Union layouts (tier1) | %union.* parsed like %struct.* (LLVM lowers unions to single-member structs); mutex arrays now sized | DONE |
| 22. Parametrized line size | tier1 --line-size N; tier2 FS_CACHE_LINE_BYTES env (clamped 16..4096) | DONE |

### Round-5 scores (23 cases, exit 0)

| Analyzer | TP | FP | FN | GAP | Precision | Recall |
|---|---|---|---|---|---|---|
| tier1 | 9 | 0 | 0 | 4 | 1.00 | 1.00 |
| tier2 | 11 | 0 | 0 | 2 | 1.00 | 1.00 |

Huron: histogram upgraded to a full HIT (H7 on thread_arg_t, both tiers);
locked_toy mutex-array H2 restored in both tiers. Recall stays 7/7.

## Round 6 — interprocedural privacy (2026-07-03)

Gemini roadmap phase 5, first slice (module-local, no LTO):

| Phase | Task | Status |
|---|---|---|
| 23. Tier2 argument privacy | escapesLocally() split out; isPrivateBase() recurses through Argument bases: address never taken + every call site passes a private value (depth-capped) | DONE |
| 24. Tier1 fixpoint | Per-function privacy seeded with proven-private params; module fixpoint over call sites; address-taken fns (thread entries, fn-ptr args) excluded | DONE |
| 25. Corpus regression | adv_tn_private_via_helper (malloc in thread fn, writes via static helper) | DONE |

### Round-6 scores (24 cases, exit 0)

| Analyzer | TP | FP | FN | GAP | Precision | Recall |
|---|---|---|---|---|---|---|
| tier1 | 9 | 0 | 0 | 4 | 1.00 | 1.00 |
| tier2 | 11 | 0 | 0 | 2 | 1.00 | 1.00 |

Huron: LocalCopies FP gone both tiers (last confirmed FP from round 1);
all 7 hits intact. Remaining suite extras: 4 plausible + 1 FP (getnextline).

## Round 7 — PARSEC validation, first C++ dataset (2026-07-04)

Branch `parsec-validation` (stacked on interproc-privacy). New tooling:
`scan.py` (label-free findings report + cross-tier agreement),
`external/build_parsec_ir.sh` (streamcluster/fluidanimate/canneal ->
merged .ll via sparse clone + llvm-link-18),
`external/parsec_ground_truth.md` (Sheriff/PREDATOR/LASER/Huron table).

Results (external_validation.md round 5): both documented streamcluster
bugs HIT both tiers (work_mem CACHE_LINE=32 stride, switch_membership
bool array) — qualified: right object, generic mechanism text. Recall
2/2. Strict precision weak on foreign C++ (tier1 0.13, tier2 0.05
strict; 0.81/0.32 counting plausibles) — first C++ input exposed gaps:

| Phase | Task | Status |
|---|---|---|
| 26. H5 clustering | 26 pairwise H5 findings for 9 statics -> one finding per estimated cache-line cluster, pairs to JSON only | TODO |
| 27. Alloca privacy | Stack allocas as private bases in interproc privacy (both tiers) — InitNeighCellList FP | TODO |
| 28. C++ alloc fns | _Znwm/_Znam in alloc lists + field-store-tolerant escape (this->member = new ...) — MTRand FP | TODO |
| 29. Tier1 %class | Parse %class.* layouts (regex ir_analyzer.py:104) — Vec3 miss, latent C++ recall hole | TODO |
| 30. pid-guard | Suppress H6 when writes dominated by tid==const compare — intshuffle/selectfeasible FPs | TODO |
| 31. Symbol names | Surface resolved base names (@work_mem) in H6 finding text | TODO |
| 32. Stride check | Insufficient-stride detection (const stride < line size) — states the actual CACHE_LINE=32 mechanism; move block-partitioned arrays to H7 text | TODO |

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
