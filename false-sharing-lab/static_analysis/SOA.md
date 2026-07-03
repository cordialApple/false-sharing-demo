# State-of-the-Art Survey: Compiler-Based / Static Detection of False Sharing in Multithreaded C Code

*Produced by the Phase-1 research worker (Sonnet). Basis for STRATEGY.md.*

## 1. Taxonomy of Existing Tools and Approaches

### 1.1 DYNAMIC (Runtime) Tools — Contrast Baseline

All of the most well-known false-sharing tools are **dynamic**: they need a real
execution with real thread interleavings and addresses.

**SHERIFF** (OOPSLA 2011, Liu & Berger) — replaces pthreads with processes, uses
OS copy-on-write to diff per-page writes per thread, compares at cache-line
granularity. ~20% overhead; `Sheriff-Protect` can auto-mitigate.
[Paper](https://people.cs.umass.edu/~emery/pubs/res005-liu.pdf) | [GitHub](https://github.com/plasma-umass/sheriff)

**PREDATOR** (PPoPP 2014, Liu et al.) — dynamic *predictive* detector: tracks
"virtual cache lines" so it can flag latent false sharing that would appear under
different allocator placement or larger line sizes. Found real issues in MySQL and
Boost. [Abstract](https://people.umass.edu/tongping/pubs/abstract-predator.html) | [DOI](https://dl.acm.org/doi/10.1145/2692916.2555244)

**Cheetah** (CGO 2016) — PMU/PEBS sampling; first to *quantify* projected speedup
of fixing an instance. [ACM DL](https://dl.acm.org/doi/10.1145/2854038.2854039)

**Feather / Featherlight** (PPoPP 2018 Best Paper) — ~3% overhead via PMU + x86
debug registers; handles multi-process shared memory; no recompilation.
[ACM DL](https://dl.acm.org/doi/10.1145/3178487.3178499) | [GitHub](https://github.com/WitchTools/Feather)

**Huron** (PLDI 2019) — hybrid detect-and-repair (Intel PT tracing + in-production
phase); regroups thread-local data; 3.82× average speedup.
[ACM DL](https://dl.acm.org/doi/10.1145/3314221.3314644) | [GitHub](https://github.com/efeslab/huron)

**Perf C2C** (Linux perf) — records HITM cache events, reports contended lines with
source attribution. Gold standard for production diagnosis; no recompilation.
[Blog](https://joemario.github.io/blog/2016/09/01/c2c-blog/) | [Red Hat docs](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/monitoring_and_managing_system_status_and_performance/detecting-false-sharing_monitoring-and-managing-system-status-and-performance)

**ThreadSanitizer** — LLVM instrumentation pass (`-fsanitize=thread`) for data
*races*, not false sharing; related but different problem.
[Docs](https://clang.llvm.org/docs/ThreadSanitizer.html)

### 1.2 STATIC (Compile-Time) Tools

**lshaz** (2025, LLVM community) — the most significant recent static tool. A
LibTooling analyzer with two layers: an AST layer (`ASTRecordLayout` +
`RecursiveASTVisitor` computing field byte offsets; flags adjacent atomics,
hot/cold co-location, line-spanning fields) and an IR layer (cross-references AST
findings against optimized IR to suppress dead operations). 15 rules; validated on
4,502 Abseil TUs; found real false sharing in LLVM's own `llvm::TrackingStatistic`.
Architecture-aware (64 B x86-64/AArch64, 128 B Apple ARM).
[LLVM Discourse](https://discourse.llvm.org/t/lshaz-a-clang-llvm-static-analyzer-for-microarchitectural-hazards/90100) | [Abseil case study](https://abokhalill.github.io/lshaz-writeup/writeups/abseil-deep-dive/)

**clang-analyzer-optin.performance.Padding** — clang-tidy checker flagging
suboptimal struct padding. Necessary-but-not-sufficient for false sharing; no
thread reasoning. [Docs](https://clang.llvm.org/extra//clang-tidy/checks/clang-analyzer/optin.performance.Padding.html)

**SharC** (PLDI 2008) — type-system checker for annotated data-sharing strategies;
safety-focused, not false-sharing-specific. [ACM DL](https://dl.acm.org/doi/10.1145/1379022.1375600)

(No tool named "LASER" was found in the literature.)

## 2. LLVM Infrastructure Enabling Static Detection

- **DataLayout / StructLayout** (`llvm/IR/DataLayout.h`): `getElementOffset(idx)`,
  `getSizeInBytes()` — determine whether two fields fall in the same 64-byte line:
  `|offset(A) - offset(B)| < 64`, both written from distinct threads.
- **GEP patterns**: struct field accesses emit `getelementptr` with constant field
  indices → map to byte offsets; enumerate `StoreInst`/`LoadInst` on GEP results.
- **Thread-entry discovery**: LLVM IR has no thread model. Heuristic: find
  `call pthread_create(_, _, fn, _)` sites; `fn` is a thread entry; transitively
  mark callees thread-reachable. Fails on runtime function pointers.
- **Alias/escape limitations**: `pthread_create` breaks the call graph via
  opaque `void*`; heap sharing is indistinguishable from thread-private without
  shape analysis; AA is intra-procedural by default; flow-insensitive.

**Consequence: purely static detection is heuristic** — it flags what *could* be
falsely shared given plausible thread assignment; it cannot prove it. This is why
all production tools are dynamic.

## 3. Implementation Routes (Ranked by Effort)

- **Route A — Python analysis of `clang -S -emit-llvm` output (lowest effort):**
  parse `.ll` text (regex or `llvmlite`). Detect struct type declarations, GEP
  field accesses, `pthread_create` entries. No LLVM dev headers. Cons: must
  replicate DataLayout alignment math; single-TU; no function-pointer tracking.
- **Route B — Out-of-tree LLVM pass via `opt -load-pass-plugin` (medium):** new
  pass manager `ModulePass` with real DataLayout/use-def/AA access. Needs
  `llvm-dev` + CMake; plugin ABI version-locked.
  [Writing an LLVM Pass](https://releases.llvm.org/18.1.7/docs/WritingAnLLVMPass.html) | [llvm-tutor](https://github.com/banach-space/llvm-tutor)
- **Route C — clang-tidy / CSA checker (high effort, best integration):** AST
  `RecordDecl` walk à la lshaz; automatic IDE integration; thread reasoning at AST
  level extremely hard.
- **Route D — libclang Python bindings (limited):** `clang.cindex` exposes field
  offsets (`clang_Type_getOffsetOf`) but no IR/call-graph view; most fragile.

## 4. Key Detection Heuristics

- **H1** — Two mutable fields of one struct within the same 64-byte bucket, both
  stored to from distinct thread-entry functions.
- **H2** — Array of small structs (`sizeof < 64`) indexed by thread id
  (variable-index GEP). The classic anti-pattern; fix is `alignas(64)`.
- **H3** — Adjacent atomics (`_Atomic`) in the same cache-line window.
- **H4** — Struct used as array element with `sizeof % 64 != 0` and no
  `aligned(64)` attribute → adjacent elements straddle lines.
- **H5** — Globals within 64 bytes in the data segment, both thread-written
  (needs linker map / LTO).
- **H6** — Hot (volatile/atomic/lock-protected) field co-located with cold fields.

## 5. Summary Comparison

| Tool | Type | Level | Thread model | Fix suggestion | FS-specific |
|---|---|---|---|---|---|
| SHERIFF | Dynamic | Runtime | pthreads | Yes | Yes |
| PREDATOR | Dynamic | Runtime+prediction | pthreads | No | Yes |
| Cheetah | Dynamic | PMU sampling | pthreads | Ranks severity | Yes |
| Feather | Dynamic | PMU + debug regs | threads+processes | No | Yes |
| Huron | Hybrid | PT tracing | pthreads | Yes | Yes |
| Perf C2C | Dynamic | HW counters | OS threads | No | Yes |
| TSan | Dynamic | IR instrumentation | happens-before | No | No (races) |
| lshaz | **Static** | AST + IR | heuristic | Guidance | Yes |
| clang-analyzer Padding | **Static** | AST | none | Guidance | No (layout) |
| SharC | Static+Dynamic | AST | annotations | No | No |
