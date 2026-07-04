# External validation: Huron benchmark suite

Date: 2026-07-02 · branch: `external-validation` · analyzers: tier1 `ir_analyzer.py` + tier2 `FalseSharingPass.so` (LLVM 18, WSL Ubuntu)

## Purpose

The in-house corpus scores (tier1/tier2 = 1.00 precision, 0 FP) are circular: the corpus
was written alongside the heuristics. This run measures both tiers against an
**independent dataset with published ground truth**: the test suite of the Huron
false-sharing repair tool (PLDI'19, github.com/efeslab/huron). Each program ships an
original (buggy) and a `_manual` (hand-fixed) version; the diff between them is the
documented false-sharing site.

## Method

- Source: `test_suites/` from a fresh `efeslab/huron` clone (7 C programs; C++/boost
  suites excluded — no boost dev headers in the WSL image).
- Compile: `clang-18 -O0 -g -pthread -S -emit-llvm` (same contract as the in-house
  corpus). `string_match` additionally needed `-include sys/time.h`
  `-Wno-implicit-function-declaration` (K&R-era implicit decl).
- Run: both analyzers via their standard CLI (`<file.ll> --json`), findings compared by
  hand against the original-vs-manual diff.
- Scoring: a **HIT** requires the analyzer to flag the exact data structure the Huron
  authors fixed. Extra findings are scored against the source code individually.

## Results

| Program | Ground-truth site (from `_manual` diff) | Tier 1 | Tier 2 |
|---|---|---|---|
| `false.c` | heap `int *array`, threads write adjacent elements | MISS | MISS |
| `histogram` | heap array of `thread_arg_t` (3096 B); fix = `char padding[40]` + `aligned_alloc(64)` | MISS | MISS |
| `linear_regression` | heap array of `lreg_args`; fix = `aligned_alloc(64)` | **HIT** (H1 on `lreg_args` fields 3–7, exactly the `SX..SXY` accumulators) | **HIT** (same) |
| `locked/toy.c` | heap `int *dynMemory`, tid-strided writes; fix = ×64 index spacing | MISS | MISS (+1 extra, see below) |
| `lockless/toy.c` | same as locked | MISS | MISS |
| `lu_ncb` (SPLASH-2) | heap `double *a` matrix; fix = `aligned_alloc(64)` | MISS (+4 extras) | MISS (+4 extras) |
| `string_match` | two per-thread `malloc(MAX_REC_LEN)` buffers landing adjacent; fix = `aligned_alloc(64)` | MISS | MISS |

**Recall vs ground truth: 1/7 (0.14) for both tiers.** In-house corpus recall was 1.00.
This is the expected gap between a corpus written for the heuristics and independent code.

### Extra findings (not the documented site)

| Finding | Assessment |
|---|---|
| H2 HIGH on `%struct.POINT_T` (2 B), `linear_regression`, both tiers | **FP.** `points[i].x/.y` are only ever *loaded* in the thread function; read-only sharing causes no invalidation traffic. Root cause: H2 fires on any variable-index GEP into a small struct and never checks for stores. |
| H2 HIGH on `%union.pthread_mutex_t` array (40 B), `locked/toy.c`, tier2 only | **Plausible but unconfirmed.** Adjacent mutexes in one cache line is a classic contention pattern, but Huron's fix did not touch the lock array, so scored as FP vs ground truth. Tier1 missed it because it does not parse union layouts. |
| H1 MEDIUM ×1 on `%struct.LocalCopies`, `lu_ncb`, both tiers | **FP.** Each thread `malloc`s its *own* `LocalCopies` instance inside `SlaveStart`; the fields are private to one thread. Root cause: H1 has no instance-privacy notion — it assumes any thread-written struct is a single shared instance. |
| H1 MEDIUM ×2 on `%struct.GlobalMemory` + ×1 on barrier `%struct.anon`, `lu_ncb`, both tiers | **Plausible but unconfirmed.** `Global->id++` really is executed by every thread (under `idlock`), adjacent to other hot fields, and the barrier struct packs mutex/cv/counter into shared lines. Real contention candidates, but not what Huron fixed → FP vs ground truth. |

Strict precision vs ground truth: tier1 2/7 findings correct (0.29), tier2 2/8 (0.25).
Treating the four "plausible" extras generously as true positives: tier1 5/7, tier2 6/8.

## Failure modes (labeled)

1. **Scalar-array gap (dominant, 4/7 misses):** `false.c`, `locked`, `lockless`,
   `lu_ncb` all false-share through plain `int*`/`double*` heap arrays indexed by thread
   id — no struct anywhere. This is the already-roadmapped H6 gap; this dataset shows it
   is the single most common real-world pattern, not an edge case.
2. **Large-struct boundary gap (new, `histogram`):** `thread_arg_t` is 3096 B — far over
   64 B, so H1/H2's small-struct logic never engages. The sharing happens at the
   *boundaries* between adjacent array elements because 3096 % 64 ≠ 0 and `malloc` gives
   no 64 B alignment. New heuristic candidate ("H7"): array-of-structs indexed by tid
   where `sizeof % 64 != 0`, flag the boundary. Extra hazard: the hot writes go through
   hoisted local pointers (`red = thread_arg->red`), so field attribution must follow
   pointer copies.
3. **Allocator-adjacency (statically out of reach):** `string_match` (and `lu_ncb`'s
   `LocalCopies`) false-share only because separate `malloc`s happen to land in one
   line. No static analyzer can see this without an allocator model; this is
   PREDATOR/dynamic-tool territory. Honest label: out of scope for the static tiers.
4. **H2 missing write requirement:** read-only shared arrays (`POINT_T`) get HIGH
   findings. Fix candidate: require at least one store through the variable-index GEP
   chain before firing.
5. **H1 missing instance-privacy:** per-thread private allocations of a struct type
   (`LocalCopies`) are indistinguishable from a shared instance. Fix candidate: track
   whether the struct pointer escapes to other threads (pthread_create arg, global) vs
   stays local to the thread that allocated it.

## Takeaways

- The one hit is a genuine, canonical Phoenix bug (`lreg_args`) found by the exact
  heuristic (H1) designed for that pattern — the pipeline works end to end on foreign IR
  with zero harness errors (7/7 programs parsed and analyzed by both tiers).
- The 1.00 in-house scores do not generalize, as predicted. External recall is 0.14.
- Priority order the data suggests: H6 (scalar arrays) closes 4 of 6 misses; the new
  boundary heuristic closes the 5th; the 6th (`string_match`) is out of static scope.
- Both FP root causes (no-write-check H2, no-privacy H1) are fixable without new
  infrastructure.

## Round 2 — after H6 + FP fixes (2026-07-03, branch `h6-round`)

Changes since round 1: H6 implemented in both tiers (variable-index store into
free-standing shared scalar array), H2/H4 now require a store through the
variable-index GEP chain, H1 skips thread-private malloc instances
(intra-function escape analysis). In-house corpus grew to 22 cases (3 new
regression cases from this dataset's failure modes); both tiers exit 0 on it.

| Program | Ground-truth site | Tier 1 | Tier 2 |
|---|---|---|---|
| `false.c` | heap `int *array` | **HIT** (H6) | **HIT** (H6) |
| `histogram` | `thread_arg_t` array boundaries | **HIT*** (H6 via hoisted `thread_arg->red` pointers) | **HIT*** (same) |
| `linear_regression` | `lreg_args` | **HIT** (H1) | **HIT** (H1) |
| `locked/toy.c` | heap `int *dynMemory` | **HIT** (H6) | **HIT** (H6) |
| `lockless/toy.c` | same | **HIT** (H6) | **HIT** (H6) |
| `lu_ncb` | heap `double *a` matrix | **HIT** (H6) | **HIT** (H6) |
| `string_match` | `key1_final`/`key2_final` buffers | **HIT*** (H6 in `compute_hashes`) | **HIT*** (same) |

**Recall vs ground truth: 7/7 (1.00) both tiers, up from 1/7 (0.14).**

*Qualified hits (right object, imprecise mechanism):* `histogram` and
`string_match` flag exactly the memory Huron's fix realigned, but H6's stated
mechanism (thread-id-indexed adjacent elements) is not the true one there
(element-boundary straddling resp. allocator adjacency). A dedicated H7
boundary heuristic would state the histogram mechanism correctly; the
string_match adjacency remains statically invisible in principle — H6 catches
it only because the buffers are globally visible and variable-index written.

### Round-1 FPs resolved

- H2 HIGH on read-only `POINT_T` (`linear_regression`): **gone** (write requirement).
- H2 HIGH on `pthread_mutex_t` array (`locked`, tier2): **gone** (write requirement; locking is calls, not stores).

### Remaining extra findings

| Finding | Assessment |
|---|---|
| H1 on `%struct.GlobalMemory` ×2 + barrier `%struct.anon` (`lu_ncb`, both tiers) | Plausible-but-unconfirmed, unchanged from round 1: real contention candidates (`Global->id++` under lock, packed barrier struct), just not what Huron fixed. |
| H1 on `%struct.LocalCopies` (`lu_ncb`, both tiers) | **Still FP.** The malloc is in `SlaveStart` but the pointer is passed to `lu()`, and the privacy check is intra-function only. Fix direction: interprocedural privacy (private-arg propagation). The corpus case `adv_tn_private_two_fields` proves the intra-function half works. |
| H6 on `(pointer) i8 array` in `getnextline` (`string_match`, both tiers after the dedup-parity fix) | FP vs ground truth: writes into the caller's line buffer; index is data-dependent, not tid-strided. |

Strict per-object precision: 7/12 (0.58) both tiers, was 0.29/0.25; counting
the three plausible `lu_ncb` extras generously: 10/12. A post-review fix pass
(token-boundary escape matching, `store atomic`/`llvm.memset` visibility,
per-alias-group escape, per-fn H6 dedup parity, privacy in H2/H4) left all 22
corpus cases and all 7 Huron hits unchanged. The 1.00 in-house corpus scores remain regression gates, not
generalization claims — but the external gap has closed from 0.14 to 1.00
recall on this suite.

## Round 3 — H7 + synchronization modeling (2026-07-03, branch `h7-round`)

Adopted from the Gemini improvement roadmap: H7 (phase 1), lock-call write
modeling (phase 4), parametrized cache-line size (phase 6a).

- **`histogram` upgrades from qualified to full HIT:** H7 now flags
  `%struct.thread_arg_t` itself (both tiers) — pthread_create hands `&args[i]`
  to each thread, 3096 % 64 ≠ 0, alignment < 64 — the exact mechanism Huron's
  padding + `aligned_alloc(64)` fix addressed. The H6 hoisted-pointer finding
  remains as a secondary signal.
- **Lock modeling restores the mutex-array finding:** `pthread_mutex_lock`
  counts as a write to the lock word, so the round-1 "plausible" H2 on
  `locked/toy.c`'s `%union.pthread_mutex_t` array is back — now in BOTH tiers
  (tier1 additionally learned to parse `%union.*` layouts, which LLVM lowers
  to single-member structs).
- In-house corpus: 23 cases, both tiers 0 FP / 0 FN, exit 0. The
  `adv_tp_mutex_data_same_line` opaque-call GAP is now a PASS in both tiers.
- Cache line size is parametrized: tier1 `--line-size N`, tier2
  `FS_CACHE_LINE_BYTES` env (verified: 128 → 16 elements/line on the 8B
  tid-array case).

Recall vs ground truth stays 7/7; `string_match` remains the one qualified
hit (allocator adjacency is statically invisible; H6 catches the right
buffers for a related-but-different reason). Extras unchanged from round 2
plus the restored mutex-array finding (plausible, not in Huron's fix).

## Round 4 — interprocedural instance privacy (2026-07-03, branch `interproc-privacy`)

Gemini roadmap phase 5, first slice (module-local, no LTO): a function
argument is thread-private when the callee's address is never taken and
**every** call site passes a value that is itself thread-private in its
caller (recursive, depth-capped). Tier1 implements this as a module-level
fixpoint seeding per-function privacy with proven-private parameters; tier2
recurses through `Argument` bases over direct call sites.

- **`LocalCopies` FP eliminated in both tiers** — the malloc in `SlaveStart`
  passed down through `lu()`/`OneSolve()` now resolves as private. This was
  the last confirmed FP from round 1.
- `lreg_args` TP intact: thread-entry parameters are address-taken via
  `pthread_create`, so they can never be argued private. All 7 hits stand.
- Corpus: 24 cases (new `adv_tn_private_via_helper` regression test), both
  tiers 0 FP / 0 FN, exit 0.

Remaining extras on the suite: three plausible `lu_ncb` findings
(`GlobalMemory` ×2, barrier `anon`), the plausible `locked` mutex-array H2,
and one FP (`getnextline` i8 buffer, data-dependent index) — the only
confirmed false positive left across the seven programs.

## Round 5 — PARSEC validation (2026-07-04, branch parsec-validation)

Second independent dataset: PARSEC 3.0 (cirosantilli mirror), programs
streamcluster, fluidanimate, canneal, compiled per
`external/build_parsec_ir.sh` contract and scanned by both tiers
(`results/scan_parsec.md`). Ground truth from the published literature
(`external/parsec_ground_truth.md`, Sheriff/PREDATOR/LASER/Huron): two
documented positives, both in streamcluster; canneal and fluidanimate are
"FS detected but insignificant" (near-negatives) in Sheriff. Every verdict
below was adjudicated against the PARSEC source in WSL and the emitted IR
(GEP-base tracing), not against finding text alone.

### streamcluster (2 ground-truth positives)

| Ground-truth site | Tier 1 | Tier 2 |
|---|---|---|
| `work_mem` (function-static `double*` in `pgain`, tid-strided `work_mem[pid*stride]`, padding macro `CACHE_LINE=32` < 64B; Sheriff/PREDATOR/LASER) | **HIT*** (H6 "(pointer) double array" in `_Z5pgain...`) | **HIT*** (same H6) |
| `switch_membership` (global `bool*`, `switch_membership[i]=1` in `pgain`; PREDATOR +4.77%) | **HIT*** (H6 "(pointer) i8 array" in `_Z5pgain...`) | **HIT*** (same H6) |

Both hits verified in the IR: every variable-index `store double` in
`_Z5pgainlP6PointsdPliP16parsec_barrier_t` traces its GEP base to a load of
`@_ZZ5pgainl...E8work_mem` (directly or via the `lower`/`gl_lower` derived
pointers), and the only variable-index `store i8` (`store i8 1, ptr %293`)
traces to `@_ZL17switch_membership` (`is_center` is load-only in `pgain`).

*Qualified hits, two ways:* (1) H6 reports "(pointer) double/i8 array" with
the function name but never surfaces the variable name, even though the base
resolves to a named global — the user must repeat the GEP trace by hand.
(2) The stated mechanism is generic tid-adjacent indexing; the actual
`work_mem` bug is an insufficient padding *stride* (`CACHE_LINE=32`, i.e.
4 doubles, half a real line), and the actual `switch_membership` mechanism is
block-range partitioning with boundary sharing (H7 shape). Right memory, right
function, imprecise story. The tier2 H5 pairs that literally name
`@..._E8work_mem` do **not** count toward hit #1: they flag the 8-byte static
*pointer slot* in the data segment, not the malloc'd buffer it points to.

### canneal (ground truth: no significant FS — true-negative case)

| Finding | Verdict |
|---|---|
| Tier 1: no findings | **Correct** (matches ground truth) |
| Tier 2: H1 MEDIUM `%class.MTRand` fields [1, 2], bucket 78 | **FP.** Each `annealer_thread::Run` has a stack-local `Rng rng` (annealer_thread.cpp:55) whose constructor does `_rng = new MTRand(seed++)` (rng.h:47) — one MTRand per thread, never shared. Fields [1, 2] really are `pNext`/`left` at offsets 4992/5000 (MersenneTwister.h typedefs `uint32` as `unsigned long`, so `mt[624]` is 4992B) and really are co-written by `reload()`/`randInt()` — but only ever by the owning thread. |

Root cause, two layers: (a) neither tier's allocation model knows C++
`operator new` — tier1 `malloc_re` and tier2 `isAllocFnName` both match only
`malloc|calloc|aligned_alloc|realloc`, so `_Znwm` is not a privacy-eligible
allocation site; (b) even with `_Znwm` modeled, the pointer is stored into the
`_rng` member field of a stack-local `Rng`, which the current escape analysis
counts as an escape. Tier1's silence is **not** a correct negative for the
right reason: its struct parser regex (`^(%(?:struct|union)\.[\w.]+)`) skips
`%class.*` types entirely, so C++ class layouts are invisible to tier1 —
a luck-based pass here and a real coverage gap everywhere else.

### fluidanimate (ground truth: FS detected but insignificant — Sheriff)

| Finding (tier) | Assessment |
|---|---|
| H2 HIGH `%union.pthread_mutex_t` array, `ComputeForcesMT` (both) | **Plausible but unconfirmed.** `mutex[index][j]` arrays of 40B mutexes, locked by different threads on neighboring border cells — classic adjacent-locks pattern; consistent with Sheriff's heavy-locking observation, no published fix. |
| H1 `%struct.parsec_barrier_t` fields [3, 4] (both) | **Plausible but unconfirmed.** All threads write the counter/flag words in `parsec_barrier_wait`; real contention, but inherent to a sync primitive (mostly true sharing). Same finding also appears in streamcluster — same assessment. |
| H1 `%struct.cellpool` fields [0-2] (both) | **Qualified plausible — wrong mechanism.** `pools = new cellpool[NUM_GRIDS]` (pthreads.cpp:139), one 24B pool per thread, each thread mutating only `pools[tid]` in the parallel phase. As stated (one shared instance, hot fields same line) it is wrong — each instance is single-writer. But 24B elements mean 2-3 per-thread pool headers share each line, so cross-*instance* FS is real; the correct shape is tid-indexed array of small structs (H2/H7), not H1. |
| H6 i32 `RebuildGridMT` (both) | **Plausible.** Verified: `++cnumPars[index]` where border-cell indices are genuinely written by multiple threads (mutex-guarded at pthreads.cpp:603-615); the lock serializes but does not stop line ping-pong. Matches Sheriff's detected-but-insignificant. |
| H6 i32 `ClearParticlesMT` (both) | **Plausible-weak.** `cnumPars[index] = 0` over the thread's own grid slab; arrays are cacheline-aligned at the start, but slab boundaries fall mid-line. Boundary-only, minor. |
| H6 i32 `InitNeighCellList` (both) | **FP.** Writes `neighCells[n]` where every caller passes a stack array `int neighCells[3*3*3]` (pthreads.cpp:698, 791) — thread-private memory. Root cause: the round-4 interprocedural privacy handles malloc results and private arguments but **not allocas** — neither tier1 (`private = malloc_regs | private_params`) nor tier2 (`isPrivateBase` handles `CallBase`/`Argument` only) seeds a non-escaping `alloca` as a private base. |
| H2 HIGH `%class.Vec3`, `RebuildGridMT` (tier2 only) | **Plausible-weak.** `cell->p[np % PARTICLES_PER_CELL] = ...` — variable index into a Vec3 array inside a `Cell`; border cells are written by multiple threads, but the index is a particle count, not a tid, so H2's stated mechanism is wrong. Tier1 missed it for the same `%class.*` parsing gap as MTRand. |

### streamcluster extra findings

| Finding (tier) | Assessment |
|---|---|
| H6 i32 `intshuffle` (both) | **FP.** Only ever called under `if (pid == 0)` (pFL, streamcluster.cpp:~1226) — single-thread phase. Runtime pid-guards are invisible to both tiers. |
| H6 i32 `selectfeasible_fast` (both) | **FP.** Source comment states "it is called only by thread 0 for now"; all `(*feasible)[i]` writes are single-thread. Same pid-guard blindness. |
| H6 i32 `pgain` (both) | **Plausible.** Verified as `center_table[i]` (GEP base `@_ZL12center_table`), block-partitioned per tid — same boundary-sharing shape as `switch_membership`, just not in the papers. |
| H2 HIGH `%struct.Point` in `pgain` (both) | **Plausible.** Threads write `points->p[i].cost/.assign` over disjoint tid blocks; 32B Points, 2 per line — block-boundary sharing (H7 shape), not documented. |
| H6 double `pspeedy` / H6 double `pkmedian` (both) | **Plausible.** `costs[pid]` (malloc'd `double*nproc`, pspeedy) and `hizs[pid] = myhiz` (calloc'd `double*nproc`, streamcluster.cpp:1511) — textbook unpadded tid-indexed reduction arrays; real FS shape, written once per phase, so perf-insignificant. |
| H6 i8 `pkmedian` (both) | **Plausible.** `is_center[...] = true` — ground-truth doc itself notes `is_center` has the same shape as `switch_membership` but is not in the papers. |
| H5 ×26 pairwise on function-statics (tier2 only) | **Unverifiable as pairs; flood.** See below. |

### The H5 pair flood

Tier2 emitted **26** pairwise H5 findings over 9 function-static globals
(`pgain`: `work_mem`, `gl_cost_of_opening_x`, `gl_number_of_centers_to_close`;
`pspeedy`: `i`, `open`, `costs`, `totalcost`; `pkmedian`: `numfeasible`,
`hizs`) — every cross-function pair of small thread-written statics. The
underlying signal is legitimate: these statics live in `.bss`, several are
genuinely written by all threads in the documented hot region, and small-
global adjacency is exactly PREDATOR territory. But the analyzer cannot know
final link layout, so each *pair* is speculative, and O(n²) enumeration turns
one observation ("9 small thread-written globals may co-reside on a few
lines") into 26 MEDIUM rows that bury the two real hits in the same table.
Fix: cluster instead of pair — group candidate globals by estimated line
occupancy (module emission order + size + alignment) and emit **one finding
per cluster** listing its members, with pair detail demoted to the JSON.
That alone shrinks this report from 30 tier2 streamcluster rows to ~6.

### Scores

Recall vs ground truth (2 documented positives, both streamcluster):
**tier1 2/2, tier2 2/2** — both qualified hits (right memory and function,
variable name not surfaced, mechanism generically stated).

Precision, distinct findings: tier1 16 findings — 2 TP, 3 confirmed FP
(`intshuffle`, `selectfeasible_fast`, `InitNeighCellList`), 11 plausible-but-
unconfirmed → strict 2/16 (**0.13**), generous (plausibles as TP) 13/16
(**0.81**). Tier2 44 findings — 2 TP, 4 confirmed FP (the three above +
MTRand), 12 plausible, 26 unverifiable H5 pairs → strict 2/44 (**0.05**),
generous 14/44 (**0.32**). Tier2's strict precision is dominated by the H5
flood; with H5 clustered to one finding per group, tier2 would be 2 TP /
4 FP / 13 other ≈ tier1's profile.

On the near-negative programs: tier1 canneal = 0 findings (correct); both
tiers' fluidanimate findings are consistent with Sheriff's
"detected-but-insignificant" verdict except the one `InitNeighCellList` FP.

### Failure modes (labeled)

1. **H5 pair explosion (26/44 tier2 findings):** all-pairs enumeration over
   co-resident small globals; needs per-line clustering (fix sketched above).
2. **pid-guard blindness (2 FPs):** `if (pid == 0) { ... }` single-thread
   phases inside thread-reachable functions look multi-threaded. A cheap
   heuristic — writes dominated by a comparison of a thread-id-like value
   against a constant — could downgrade these.
3. **Alloca privacy gap (1 FP):** stack arrays passed to helpers
   (`neighCells`) are not seeded as private bases in either tier's
   interprocedural privacy. Straightforward extension of the round-4 work.
4. **`operator new` not an allocation site (1 FP):** `_Znwm`/`_Znam` missing
   from both tiers' alloc-function lists, so C++ heap objects can never be
   proven thread-private (MTRand). Also needs field-store-tolerant escape
   handling for the `this->_rng = new ...` idiom.
5. **`%class.*` invisible to tier1:** the struct-decl regex parses only
   `%struct.`/`%union.`. Tier1 missed `%class.Vec3` and would miss any C++
   class-typed positive; the canneal "clean pass" was luck, not judgment.
6. **Findings don't name the variable:** H6 resolves GEP bases to named
   globals internally but reports only "(pointer) double array" + function.
   Surfacing the resolved symbol (`work_mem`, `switch_membership`) would have
   made both ground-truth hits self-evident without manual IR tracing.
7. **Mechanism precision:** the `work_mem` bug is specifically an
   insufficient compile-time padding stride (`CACHE_LINE=32` vs 64B lines) —
   a detectable pattern (stride arithmetic from a constant < line size) that
   H6's generic message does not capture; `switch_membership`/`center_table`/
   `Point` are block-boundary (H7) shapes reported under H6/H2 stories.

### Takeaways

- The two canonical streamcluster bugs — including the `CACHE_LINE 32` bug
  still shipping in PARSEC 3.0 — are caught by both tiers with zero harness
  errors on foreign C++ IR. That is the headline positive.
- The near-negatives behave as ground truth predicts: nothing significant in
  canneal (tier1), locking-era noise in fluidanimate.
- The five confirmed FPs have three small, mechanical root causes (allocas,
  `_Znwm`, pid-guards); none require new infrastructure.
- Presentation, not detection, is now the bigger gap: H5 flooding and
  unnamed H6 arrays make a correct scan read worse than it is.

## Reproduce

```sh
# in WSL, from repo root
sh false-sharing-lab/static_analysis/external/build_huron_ir.sh
# then, from false-sharing-lab/static_analysis/
python ir_analyzer.py external/huron_ir/<prog>.ll --json
python tier2_analyzer.py external/huron_ir/<prog>.ll --json
```
