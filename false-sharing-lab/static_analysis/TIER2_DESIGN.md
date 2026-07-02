# Tier-2 Design — Out-of-Tree LLVM Pass for False-Sharing Detection

*Phase-6 synthesis by the orchestrator. Companion to STRATEGY.md (Tier 1).*

## Reframed project goal

The lab is an **experimentation platform for developing robust static
false-sharing detection heuristics**. Tier 1 (textual IR analysis) and Tier 2
(real LLVM pass) are two analyzer implementations scored against a shared
labeled corpus by `evaluate.py`. Heuristics graduate by earning precision/recall
on the corpus, not by argument.

## Why a real pass (what Tier 1 cannot do)

| Capability | Tier 1 (regex) | Tier 2 (LLVM API) |
|---|---|---|
| Field offsets | hand-rolled natural-alignment math | exact `DataLayout::getStructLayout()` |
| Access tracking | line-oriented regex on -O0 IR | use-def chains; survives -O1/-O2 |
| Atomics (H3) | not implemented | `AtomicRMWInst`/`StoreInst::isAtomic()` |
| Globals (H5) | not implemented | module-level `GlobalVariable` scan |
| Thread reachability | name-based call regex | real call-graph walk |

## Architecture

```
static_analysis/
  tier2_pass/
    CMakeLists.txt          <- find_package(LLVM 18 REQUIRED CONFIG)
    FalseSharingPass.cpp    <- new-PM ModulePass plugin, heuristics modular
    build/                  <- WSL cmake build tree (gitignored)
  tier2_analyzer.py         <- CLI wrapper: same contract as ir_analyzer.py
                               (python tier2_analyzer.py <file.ll> --json)
```

The wrapper runs `opt -load-pass-plugin=.../FalseSharingPass.so
-passes=false-sharing -disable-output <file.ll>` inside WSL and forwards the
pass's JSON (pass prints to stderr or a report file; wrapper normalizes to the
Tier-1 stdout schema so `evaluate.py` can register both analyzers uniformly).

## Heuristics (modular — each an independent check emitting findings)

- **H2** (HIGH): variable-index GEP into array of struct with
  `StructLayout::getSizeInBytes() < 64`, inside a thread-reachable function.
- **H1** (MEDIUM): two distinct fields of one struct in the same 64-byte bucket
  (exact offsets), both targets of stores in thread-reachable code.
- **H3** (HIGH): two atomic-accessed fields (atomic store / atomicrmw / cmpxchg
  through GEPs) of one struct within the same 64-byte bucket.
- **H4** (LOW): struct used as array element, size % 64 != 0, no align(64).
- **H5** (MEDIUM): two small (< 64B) non-const globals both written from
  DIFFERENT thread-reachable functions. Statically we cannot know final data
  segment addresses — severity reflects that this is placement-dependent.

Thread reachability: collect third args of `pthread_create` calls, transitively
close over the call graph. Functions only reachable from `main` are not
thread-reachable (single-thread context).

## Output schema

Identical JSON shape to `ir_analyzer.py --json`:
`{file, thread_entries, thread_reachable, struct_layouts, findings:[{heuristic,
severity, struct, struct_size_bytes, elements_per_cache_line, thread_fn, detail,
fix}]}` — for H5 use the global's name in `struct` (prefixed `@`).

## Build & invocation (WSL)

```bash
cd static_analysis/tier2_pass
cmake -B build -DCMAKE_BUILD_TYPE=Release . && cmake --build build
opt-18 -load-pass-plugin=build/FalseSharingPass.so \
       -passes=false-sharing -disable-output ../ir/false_sharing.ll
```

Note: plugin must be built against the same LLVM as `opt` (18.1.3, apt). ABI is
version-locked — rebuilding is expected per LLVM upgrade.

## Acceptance (before integration into evaluate.py)

1. Plugin builds clean under WSL LLVM 18.
2. On `ir/false_sharing.ll`: H2/HIGH on `%struct.unpadded_counter_t` naming
   `worker_unpadded`; `%struct.padded_counter_t` clean.
3. Wrapper `tier2_analyzer.py ir/false_sharing.ll --json` emits schema-valid JSON.
4. Also passes on IR compiled at -O1 (where Tier 1's -O0 regexes may not) —
   demonstrates the robustness advantage.

## Worker assignment

| Task | Worker | Rationale |
|---|---|---|
| Corpus + evaluate.py | Sonnet | Well-templated Python/C, parallel with pass |
| Tier-2 C++ pass | **Opus** | LLVM C++ API, new-PM plugin ABI, use-def walking — the hardest task in the lab |
| Integration + scoring both tiers | Orchestrator | Steering + honest verification |
