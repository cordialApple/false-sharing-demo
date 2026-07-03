// BUILD REAL LLVM PASS. TIER 2. STRONGER THAN REGEX TIER.
// USE LLVM EYES: DataLayout KNOW TRUE OFFSET. USE-DEF CHAIN FOLLOW STORE.
// WALK CALL GRAPH FROM PTHREAD_CREATE. FIND THREAD LAND FUNCTION.
// SPIT JSON SAME SHAPE AS TIER 1. AGENT EAT SAME FOOD FROM BOTH TIER.
//
// LLVM 18 = OPAQUE POINTER. ptr EVERYWHERE. GET STRUCT TYPE FROM
// GEPOperator::getSourceElementType(). NOT FROM POINTER. POINTER KNOW NOTHING.

#include "llvm/IR/Module.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/Operator.h"
#include "llvm/IR/DataLayout.h"
#include "llvm/IR/GlobalVariable.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"
#include "llvm/Support/raw_ostream.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/FormatVariadic.h"
#include "llvm/ADT/SmallPtrSet.h"
#include "llvm/Analysis/ValueTracking.h"

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <vector>

using namespace llvm;

// CACHE LINE = 64 BYTE. UNIVERSAL LAW OF PROCESSOR LAND.
// TWO THREAD TOUCH SAME 64 BYTE. LINE PING PONG BETWEEN CORE. VERY SLOW.
static const uint64_t CACHE_LINE_BYTES = 64;

namespace {

// ------------------------------------------------------------------------
// FINDING = ONE WARN FOR HUMAN. MIRROR TIER 1 JSON SHAPE EXACT.
// ------------------------------------------------------------------------
struct Finding {
  std::string heuristic;         // "H1".."H5"
  std::string severity;          // "HIGH" / "MEDIUM" / "LOW"
  std::string structName;        // "%struct.X" OR "@glob" FOR H5
  int64_t structSizeBytes = 0;
  bool hasEPL = false;           // elements_per_cache_line PRESENT?
  int64_t epl = 0;
  bool hasThreadFn = false;      // thread_fn PRESENT? ELSE JSON null
  std::string threadFn;
  std::string detail;
  std::string fix;
};

// SEVERITY RANK. SORT LOUD WARN FIRST. STABLE DIFF.
static int sevRank(const std::string &s) {
  if (s == "HIGH") return 0;
  if (s == "MEDIUM") return 1;
  if (s == "LOW") return 2;
  return 9;
}

// ------------------------------------------------------------------------
// SHARED CONTEXT. EVERY HEURISTIC EAT FROM SAME BOWL. ADD NEW HEURISTIC EASY.
// ------------------------------------------------------------------------
struct FSContext {
  Module &M;
  const DataLayout &DL;
  // THREAD ENTRY FUNCTION NAME. DISCOVERY ORDER. FROM PTHREAD_CREATE ARG 3.
  std::vector<std::string> threadEntries;
  // ALL FUNCTION THREAD CAN REACH. ENTRY PLUS TRANSITIVE CALLEE.
  SmallPtrSet<Function *, 16> threadReachable;
  std::vector<Finding> findings;

  explicit FSContext(Module &Mod) : M(Mod), DL(Mod.getDataLayout()) {}

  bool isThreadReachable(Function *F) const {
    return threadReachable.count(F) != 0;
  }
};

// PRINT LLVM TYPE AS STRING. "i64", "[56 x i8]", "ptr", "%struct.foo".
// MATCH TIER 1 TYPE WORD EXACT.
static std::string typeToString(Type *T) {
  std::string s;
  raw_string_ostream os(s);
  T->print(os);
  return os.str();
}

// STRUCT TYPE NAME OUT. LLVM SAY "struct.foo". PREPEND % LIKE TIER 1.
static std::string structKey(StructType *ST) {
  if (ST->hasName())
    return ("%" + ST->getName()).str();
  return "%<literal_struct>";
}

// ------------------------------------------------------------------------
// GEP DECODE. PULL OUT WHAT MATTER FOR FALSE SHARING FROM ONE GEP.
//   - structTy: SOURCE ELEMENT STRUCT (nullptr IF SOURCE NOT STRUCT).
//   - variableArrayIndex: FIRST INDEX NOT CONSTANT -> ARRAY INDEX BY VARIABLE.
//       -O0 SEPARATE:  gep %struct.X, ptr %p, i64 %var            (1 index)
//       -O1 MERGED:    gep %struct.X, ptr %p, i64 %var, i32 N     (2 index)
//   - hasFieldIndex + fieldIndex: LAST CONSTANT INDEX = FIELD NUMBER.
//       gep %struct.X, ptr %p, i32 0, i32 N   -> FIELD N
// ------------------------------------------------------------------------
struct GepInfo {
  StructType *structTy = nullptr;
  bool variableArrayIndex = false;
  bool hasFieldIndex = false;
  unsigned fieldIndex = 0;
};

static GepInfo analyzeGep(GEPOperator *G) {
  GepInfo info;
  Type *srcTy = G->getSourceElementType();

  // SHAPE A: SOURCE IS STRUCT DIRECT. MALLOC-POINTER SHAPE.
  //   gep %struct.X, ptr %p, i64 %var           (ARRAY WALK)
  //   gep %struct.X, ptr %p, i32 0, i32 N       (FIELD ACCESS)
  if (auto *ST = dyn_cast<StructType>(srcTy)) {
    info.structTy = ST;

    // FIRST INDEX = OPERAND 1 (OPERAND 0 IS POINTER). NON-CONST = ARRAY WALK.
    Value *idx0 = G->getOperand(1);
    if (!isa<ConstantInt>(idx0))
      info.variableArrayIndex = true;

    // FIELD INDEX = LAST INDEX IF >= 2 INDICES AND CONSTANT.
    unsigned nOps = G->getNumOperands(); // ptr + N indices
    if (nOps >= 3) {
      if (auto *ci = dyn_cast<ConstantInt>(G->getOperand(nOps - 1))) {
        info.hasFieldIndex = true;
        info.fieldIndex = (unsigned)ci->getZExtValue();
      }
    }
    return info;
  }

  // SHAPE B: SOURCE IS FIXED ARRAY OF STRUCT. GLOBAL-ARRAY SHAPE.
  //   gep [4 x %struct.X], ptr @g, i64 0, i64 %var
  // OPERAND 2 = SLOT INDEX INTO ARRAY DIMENSION. NON-CONST = THREAD-ID WALK.
  // THE lshaz TrackingStatistic PATTERN. GLOBAL ARRAY OF SMALL STAT STRUCT.
  // ELEMENT MUST BE STRUCT. SCALAR ARRAY ([8 x i64]) NOT H2 BUSINESS --
  // THAT IS THE LABELED H6 GAP. NOT FIRE THERE.
  if (auto *AT = dyn_cast<ArrayType>(srcTy)) {
    auto *ST = dyn_cast<StructType>(AT->getElementType());
    if (!ST)
      return info; // ARRAY OF SCALAR. WALK AWAY.
    info.structTy = ST;
    if (G->getNumOperands() >= 3 && !isa<ConstantInt>(G->getOperand(2)))
      info.variableArrayIndex = true;
    // NO hasFieldIndex HERE. TRAILING INDEX IS ARRAY SLOT, NOT STRUCT FIELD.
    // CONSTANT SLOT INDEX = ONE FIXED ELEMENT = NOT A FINDING. STAY QUIET.
    return info;
  }

  return info; // NOT STRUCT, NOT ARRAY-OF-STRUCT. NOT CARE.
}

// GET STRUCT FIELD FROM A MEMORY POINTER (STORE / ATOMIC TARGET).
// TWO PATH. PRECISE PATH FIRST. FALLBACK PATH IF PRECISE FAIL.
//
// PATH 1 (PRECISE, OFFSET-BASED): WALK BACK THROUGH CONSTANT OFFSET
// (GEP INSTR, CONSTEXPR GEP, OR NONE) TO A BASE OBJECT. IF BASE IS
// STRUCT-TYPED GLOBAL OR ALLOCA, MAP BYTE OFFSET TO FIELD WITH EXACT
// StructLayout. CATCH BARE-POINTER FIELD 0 ACCESS (NO GEP AT ALL).
//
// PATH 2 (FALLBACK, TYPE-BASED): SOMETIMES BASE NOT RESOLVABLE. EXAMPLE:
// STRUCT POINTER ARRIVE THROUGH OPAQUE void* THREAD ARG. p = (struct X*)arg;
// p->a++. BASE IS FUNCTION ARGUMENT. NOT GLOBAL. NOT ALLOCA. PATH 1 BLIND.
// BUT THE GEP ITSELF STILL SAY WHICH STRUCT: getSourceElementType() IS
// StructType, TRAILING CONSTANT INDEX IS FIELD. TRUST THE GEP TYPE.
// BARE ARG POINTER WITH NO GEP AND NO TYPE HINT: NOT GUESS. DROP IT.
static bool getStructField(const DataLayout &DL, Value *ptr, StructType *&st,
                           unsigned &fieldIdx) {
  // PATH 1: OFFSET MATH FROM RESOLVABLE BASE OBJECT. MOST PRECISE.
  APInt off(DL.getIndexTypeSizeInBits(ptr->getType()), 0);
  Value *base = ptr->stripAndAccumulateConstantOffsets(
      DL, off, /*AllowNonInbounds=*/true);

  StructType *baseStruct = nullptr;
  if (auto *GV = dyn_cast<GlobalVariable>(base))
    baseStruct = dyn_cast<StructType>(GV->getValueType());
  else if (auto *AI = dyn_cast<AllocaInst>(base))
    baseStruct = dyn_cast<StructType>(AI->getAllocatedType());

  if (baseStruct) {
    uint64_t byteOff = off.getZExtValue();
    const StructLayout *SL = DL.getStructLayout(baseStruct);
    if (byteOff >= SL->getSizeInBytes())
      return false; // OFFSET PAST STRUCT END. NOT A FIELD OF THIS STRUCT.
    st = baseStruct;
    fieldIdx = SL->getElementContainingOffset(byteOff);
    return true;
  }

  // PATH 2: BASE UNKNOWN (E.G. void* ARG). TRUST GEP SOURCE STRUCT TYPE.
  // WORK FOR GEP INSTRUCTION AND CONSTEXPR GEP BOTH (GEPOperator SEE BOTH).
  if (auto *G = dyn_cast<GEPOperator>(ptr)) {
    GepInfo gi = analyzeGep(G);
    if (gi.structTy && gi.hasFieldIndex &&
        gi.fieldIndex < gi.structTy->getNumElements()) {
      st = gi.structTy;
      fieldIdx = gi.fieldIndex;
      return true;
    }
  }
  return false; // NO BASE, NO TYPED GEP. NOT GUESS.
}

// ------------------------------------------------------------------------
// WRITE-THROUGH CHECK (HURON LESSON: READ-ONLY SHARING IS FREE).
// TRUE IF SOME STORE/ATOMIC WRITES THROUGH root OR A POINTER DERIVED FROM
// IT (GEP/CAST/PHI/SELECT CHAIN, PLUS -O0 PARK-IN-ALLOCA-AND-RELOAD).
// ------------------------------------------------------------------------
static bool hasStoreThrough(Value *root) {
  SmallPtrSet<Value *, 16> seen;
  SmallVector<Value *, 16> wl{root};
  while (!wl.empty()) {
    Value *v = wl.pop_back_val();
    if (!seen.insert(v).second)
      continue;
    for (User *u : v->users()) {
      if (auto *SI = dyn_cast<StoreInst>(u)) {
        if (SI->getPointerOperand() == v)
          return true;
        // POINTER SAVED TO LOCAL SLOT. FOLLOW THE RELOADS.
        if (SI->getValueOperand() == v)
          if (auto *AI = dyn_cast<AllocaInst>(SI->getPointerOperand()))
            for (User *au : AI->users())
              if (auto *LI = dyn_cast<LoadInst>(au))
                wl.push_back(LI);
      } else if (auto *RMW = dyn_cast<AtomicRMWInst>(u)) {
        if (RMW->getPointerOperand() == v)
          return true;
      } else if (auto *CX = dyn_cast<AtomicCmpXchgInst>(u)) {
        if (CX->getPointerOperand() == v)
          return true;
      } else if (isa<GetElementPtrInst>(u) || isa<BitCastInst>(u) ||
                 isa<PHINode>(u) || isa<SelectInst>(u)) {
        wl.push_back(cast<Value>(u));
      }
    }
  }
  return false;
}

// ------------------------------------------------------------------------
// BASE RESOLUTION THROUGH -O0 ALLOCA SLOTS. getUnderlyingObject STOPS AT A
// LOAD; IF THAT LOAD READS A LOCAL SLOT WITH EXACTLY ONE STORED VALUE,
// CHASE THAT VALUE. p = malloc(); USE p->f  RESOLVES TO THE malloc CALL.
// ------------------------------------------------------------------------
static Value *resolveBase(Value *p, int depth = 0) {
  Value *base = getUnderlyingObject(p);
  if (depth > 8)
    return base;
  if (auto *LI = dyn_cast<LoadInst>(base)) {
    if (auto *AI = dyn_cast<AllocaInst>(
            getUnderlyingObject(LI->getPointerOperand()))) {
      Value *stored = nullptr;
      for (User *u : AI->users())
        if (auto *SI = dyn_cast<StoreInst>(u))
          if (SI->getPointerOperand() == AI) {
            if (stored)
              return base; // TWO STORES. AMBIGUOUS. STOP HERE.
            stored = SI->getValueOperand();
          }
      if (stored)
        return resolveBase(stored, depth + 1);
    }
  }
  return base;
}

static bool isAllocFnName(StringRef n) {
  return n == "malloc" || n == "calloc" || n == "aligned_alloc" ||
         n == "realloc";
}

// ------------------------------------------------------------------------
// INSTANCE PRIVACY (HURON lu_ncb LocalCopies LESSON). BASE IS PRIVATE TO
// THE CURRENT THREAD IF IT IS A malloc-FAMILY CALL IN THIS VERY FUNCTION
// WHOSE RESULT NEVER ESCAPES TO ANOTHER THREAD: NOT STORED OUTSIDE LOCAL
// ALLOCAS, NOT HANDED TO pthread_create, NOT RETURNED. OTHER DIRECT CALLS
// (free, SAME-THREAD HELPERS) DO NOT CROSS A THREAD BOUNDARY.
// ------------------------------------------------------------------------
static bool isThreadPrivateAlloc(Value *base, Function *F) {
  auto *CB = dyn_cast<CallBase>(base);
  if (!CB || CB->getFunction() != F)
    return false;
  Function *callee = CB->getCalledFunction();
  if (!callee || !isAllocFnName(callee->getName()))
    return false;

  SmallPtrSet<Value *, 16> seen;
  SmallVector<Value *, 16> wl{CB};
  while (!wl.empty()) {
    Value *v = wl.pop_back_val();
    if (!seen.insert(v).second)
      continue;
    for (User *u : v->users()) {
      if (auto *SI = dyn_cast<StoreInst>(u)) {
        if (SI->getValueOperand() == v) {
          auto *AI = dyn_cast<AllocaInst>(
              getUnderlyingObject(SI->getPointerOperand()));
          if (!AI)
            return false; // STORED OUTSIDE A LOCAL SLOT. ESCAPED.
          for (User *au : AI->users())
            if (auto *LI = dyn_cast<LoadInst>(au))
              wl.push_back(LI);
        }
      } else if (isa<ReturnInst>(u)) {
        return false;
      } else if (auto *CB2 = dyn_cast<CallBase>(u)) {
        Function *cal = CB2->getCalledFunction();
        if (cal && cal->getName() == "pthread_create")
          return false;
      } else if (isa<GetElementPtrInst>(u) || isa<BitCastInst>(u) ||
                 isa<PHINode>(u) || isa<SelectInst>(u)) {
        wl.push_back(cast<Value>(u));
      }
    }
  }
  return true;
}

// ========================================================================
// STEP 1 -- THREAD REACHABILITY.
// FIND PTHREAD_CREATE. TAKE ARG #2 (0-BASED THIRD PARAM). STRIP CAST.
// THAT FUNCTION IS THREAD ENTRY. THEN WALK CALL GRAPH. EVERY DIRECT CALLEE
// ALSO THREAD LAND.
// ========================================================================
static void discoverThreadReachable(FSContext &Ctx) {
  std::vector<Function *> worklist;

  for (Function &F : Ctx.M) {
    for (BasicBlock &BB : F) {
      for (Instruction &I : BB) {
        auto *CB = dyn_cast<CallBase>(&I);
        if (!CB)
          continue;
        Function *callee = CB->getCalledFunction();
        if (!callee || callee->getName() != "pthread_create")
          continue;
        if (CB->arg_size() < 3)
          continue;
        // ARG #2 = THE THREAD START ROUTINE. MAY WEAR BITCAST HAT. STRIP IT.
        Value *entryArg = CB->getArgOperand(2)->stripPointerCasts();
        auto *entryFn = dyn_cast<Function>(entryArg);
        if (!entryFn)
          continue;
        std::string name = entryFn->getName().str();
        if (std::find(Ctx.threadEntries.begin(), Ctx.threadEntries.end(),
                      name) == Ctx.threadEntries.end())
          Ctx.threadEntries.push_back(name);
        if (Ctx.threadReachable.insert(entryFn).second)
          worklist.push_back(entryFn);
      }
    }
  }

  // TRANSITIVE CLOSURE. CHASE DIRECT CALL LIKE HUNT. SKIP DECL AND INTRINSIC.
  while (!worklist.empty()) {
    Function *F = worklist.back();
    worklist.pop_back();
    for (BasicBlock &BB : *F) {
      for (Instruction &I : BB) {
        auto *CB = dyn_cast<CallBase>(&I);
        if (!CB)
          continue;
        Function *callee = CB->getCalledFunction();
        if (!callee || callee->isDeclaration())
          continue;
        if (callee->getName().starts_with("llvm."))
          continue;
        if (Ctx.threadReachable.insert(callee).second)
          worklist.push_back(callee);
      }
    }
  }
}

// SORT THREAD FUNCTION BY NAME. DETERMINISTIC SCAN ORDER. STABLE PICK OF fn.
static std::vector<Function *> sortedThreadFns(FSContext &Ctx) {
  std::vector<Function *> v(Ctx.threadReachable.begin(),
                            Ctx.threadReachable.end());
  std::sort(v.begin(), v.end(), [](Function *a, Function *b) {
    return a->getName() < b->getName();
  });
  return v;
}

// ========================================================================
// HEURISTIC H2 (HIGH) -- ARRAY OF SMALL STRUCT INDEXED BY VARIABLE.
// GEP WITH NON-CONSTANT ARRAY INDEX, SOURCE STRUCT SIZE < 64, IN THREAD LAND.
// CLASSIC FALSE SHARING: counters[tid].value++. ADJACENT ELEMENT SHARE LINE.
// CROSS-HEURISTIC SUPPRESSION NOT HERE. THAT LIVE IN applySuppression.
// ========================================================================
static void runH2(FSContext &Ctx) {
  // LOCAL DEDUPE ONLY. MANY GEP ON SAME STRUCT = ONE H2 WARN.
  std::set<std::string> flagged;
  for (Function *F : sortedThreadFns(Ctx)) {
    if (F->isDeclaration())
      continue;
    for (BasicBlock &BB : *F) {
      for (Instruction &I : BB) {
        auto *GEP = dyn_cast<GetElementPtrInst>(&I);
        if (!GEP)
          continue;
        GepInfo gi = analyzeGep(cast<GEPOperator>(GEP));
        if (!gi.structTy || !gi.variableArrayIndex)
          continue;
        // WRITE REQUIREMENT. READ-ONLY VAR-INDEX SCAN IS HARMLESS.
        if (!hasStoreThrough(GEP))
          continue;
        std::string key = structKey(gi.structTy);
        uint64_t sz = Ctx.DL.getStructLayout(gi.structTy)->getSizeInBytes();
        if (sz >= CACHE_LINE_BYTES)
          continue;
        if (flagged.count(key))
          continue; // ALREADY WARNED THIS STRUCT. ONE WARN ENOUGH.
        flagged.insert(key);

        int64_t epl = sz > 0 ? (int64_t)(CACHE_LINE_BYTES / sz) : 1;
        std::string fn = F->getName().str();
        Finding f;
        f.heuristic = "H2";
        f.severity = "HIGH";
        f.structName = key;
        f.structSizeBytes = (int64_t)sz;
        f.hasEPL = true;
        f.epl = epl;
        f.hasThreadFn = true;
        f.threadFn = fn;
        f.detail = formatv(
            "Variable-index array access into {0} (size={1}B < {2}B). "
            "Function '{3}' indexes array of {0} by thread id -- adjacent "
            "elements ({4} fit per {2}B cache line) share a cache line. "
            "Concurrent writes from different threads cause line ping-pong.",
            key, sz, CACHE_LINE_BYTES, fn, epl).str();
        f.fix = formatv(
            "Pad {0} to {1} bytes: add 'char padding[{1} - sizeof(struct)]' "
            "or annotate with '__attribute__((aligned(64)))' / 'alignas(64)'.",
            key, CACHE_LINE_BYTES).str();
        Ctx.findings.push_back(std::move(f));
      }
    }
  }
}

// ========================================================================
// HEURISTIC H1 (MEDIUM) -- TWO FIELD SAME 64B BUCKET, BOTH STORED IN THREAD.
// USE EXACT StructLayout OFFSET. NOT GUESS.
// H2-BEATS-H1 SUPPRESSION LIVE IN applySuppression. NOT HERE.
// ========================================================================
static void runH1(FSContext &Ctx) {
  // struct -> fieldIdx -> set of thread fn name (NON-ATOMIC STORE ONLY).
  std::map<std::string, std::map<unsigned, std::set<std::string>>> acc;
  std::map<std::string, StructType *> keyToTy;

  for (Function *F : sortedThreadFns(Ctx)) {
    if (F->isDeclaration())
      continue;
    for (BasicBlock &BB : *F) {
      for (Instruction &I : BB) {
        auto *SI = dyn_cast<StoreInst>(&I);
        if (!SI || SI->isAtomic())
          continue; // ATOMIC BELONG TO H3.
        StructType *st = nullptr;
        unsigned fi = 0;
        if (!getStructField(Ctx.DL, SI->getPointerOperand(), st, fi))
          continue;
        // PER-THREAD PRIVATE INSTANCE CANNOT FALSE-SHARE WITH ITSELF.
        if (isThreadPrivateAlloc(resolveBase(SI->getPointerOperand()), F))
          continue;
        acc[structKey(st)][fi].insert(F->getName().str());
        keyToTy[structKey(st)] = st;
      }
    }
  }

  for (auto &kv : acc) {
    const std::string &key = kv.first;
    StructType *st = keyToTy[key];
    const StructLayout *SL = Ctx.DL.getStructLayout(st);
    uint64_t structSz = SL->getSizeInBytes();

    // GROUP FIELD BY CACHE-LINE BUCKET USING EXACT OFFSET.
    std::map<uint64_t, std::set<unsigned>> buckets;
    std::map<uint64_t, std::set<std::string>> bucketFns;
    for (auto &fkv : kv.second) {
      unsigned fi = fkv.first;
      if (fi >= st->getNumElements())
        continue;
      uint64_t off = SL->getElementOffset(fi);
      uint64_t b = off / CACHE_LINE_BYTES;
      buckets[b].insert(fi);
      for (const std::string &fn : fkv.second)
        bucketFns[b].insert(fn);
    }

    for (auto &bkv : buckets) {
      if (bkv.second.size() < 2)
        continue; // NEED TWO DISTINCT FIELD IN ONE LINE.
      uint64_t b = bkv.first;
      std::string fieldList;
      for (unsigned fi : bkv.second) {
        if (!fieldList.empty())
          fieldList += ", ";
        fieldList += std::to_string(fi);
      }
      std::string fnList;
      for (const std::string &fn : bucketFns[b]) {
        if (!fnList.empty())
          fnList += ", ";
        fnList += fn;
      }
      Finding f;
      f.heuristic = "H1";
      f.severity = "MEDIUM";
      f.structName = key;
      f.structSizeBytes = (int64_t)structSz;
      f.hasEPL = false;
      f.hasThreadFn = true;
      f.threadFn = fnList;
      f.detail = formatv(
          "Fields [{0}] of {1} occupy cache-line bucket {2} (offset {3}-{4}B) "
          "and are both written from thread-reachable code.",
          fieldList, key, b, b * CACHE_LINE_BYTES,
          (b + 1) * CACHE_LINE_BYTES - 1).str();
      f.fix = formatv(
          "Split hot fields of {0} into a separate struct, or insert padding "
          "to push fields to different cache lines.", key).str();
      Ctx.findings.push_back(std::move(f));
    }
  }
}

// ========================================================================
// HEURISTIC H3 (HIGH) -- TWO ATOMIC-ACCESSED FIELD IN SAME 64B BUCKET.
// ATOMIC STORE / atomicrmw / cmpxchg THROUGH FIELD GEP. TRUE SHARING SMELL
// PLUS FALSE SHARING: ATOMIC ON ADJACENT FIELD STILL BOUNCE THE LINE.
// ========================================================================
static void runH3(FSContext &Ctx) {
  std::map<std::string, std::map<unsigned, std::set<std::string>>> acc;
  std::map<std::string, StructType *> keyToTy;

  auto record = [&](Value *ptr, Function *F) {
    StructType *st = nullptr;
    unsigned fi = 0;
    if (!getStructField(Ctx.DL, ptr, st, fi))
      return;
    acc[structKey(st)][fi].insert(F->getName().str());
    keyToTy[structKey(st)] = st;
  };

  for (Function *F : sortedThreadFns(Ctx)) {
    if (F->isDeclaration())
      continue;
    for (BasicBlock &BB : *F) {
      for (Instruction &I : BB) {
        if (auto *SI = dyn_cast<StoreInst>(&I)) {
          if (SI->isAtomic())
            record(SI->getPointerOperand(), F);
        } else if (auto *RMW = dyn_cast<AtomicRMWInst>(&I)) {
          record(RMW->getPointerOperand(), F);
        } else if (auto *CX = dyn_cast<AtomicCmpXchgInst>(&I)) {
          record(CX->getPointerOperand(), F);
        }
      }
    }
  }

  for (auto &kv : acc) {
    const std::string &key = kv.first;
    StructType *st = keyToTy[key];
    const StructLayout *SL = Ctx.DL.getStructLayout(st);
    uint64_t structSz = SL->getSizeInBytes();

    std::map<uint64_t, std::set<unsigned>> buckets;
    std::map<uint64_t, std::set<std::string>> bucketFns;
    for (auto &fkv : kv.second) {
      unsigned fi = fkv.first;
      if (fi >= st->getNumElements())
        continue;
      uint64_t b = SL->getElementOffset(fi) / CACHE_LINE_BYTES;
      buckets[b].insert(fi);
      for (const std::string &fn : fkv.second)
        bucketFns[b].insert(fn);
    }

    for (auto &bkv : buckets) {
      if (bkv.second.size() < 2)
        continue;
      uint64_t b = bkv.first;
      std::string fieldList;
      for (unsigned fi : bkv.second) {
        if (!fieldList.empty())
          fieldList += ", ";
        fieldList += std::to_string(fi);
      }
      std::string fnList;
      for (const std::string &fn : bucketFns[b]) {
        if (!fnList.empty())
          fnList += ", ";
        fnList += fn;
      }
      Finding f;
      f.heuristic = "H3";
      f.severity = "HIGH";
      f.structName = key;
      f.structSizeBytes = (int64_t)structSz;
      f.hasEPL = false;
      f.hasThreadFn = true;
      f.threadFn = fnList;
      f.detail = formatv(
          "Atomic-accessed fields [{0}] of {1} occupy cache-line bucket {2} "
          "(offset {3}-{4}B). Atomics on distinct fields in one line still "
          "bounce the line between cores.",
          fieldList, key, b, b * CACHE_LINE_BYTES,
          (b + 1) * CACHE_LINE_BYTES - 1).str();
      f.fix = formatv(
          "Place each atomic field of {0} on its own cache line "
          "(alignas(64) or separate padded structs).", key).str();
      Ctx.findings.push_back(std::move(f));
    }
  }
}

// ========================================================================
// HEURISTIC H4 (LOW) -- STRUCT USED AS VARIABLE-INDEX ARRAY ELEMENT IN
// THREAD-REACHABLE CODE, SIZE % 64 != 0, NO >=64 ALIGNMENT. ELEMENTS
// STRADDLE CACHE LINE.
// THREAD GUARD SAME AS H2: SINGLE-THREAD CODE CANNOT FALSE-SHARE.
// NO PTHREAD_CREATE = NO THREAD LAND = H4 SILENT. NO FP ON SEQUENTIAL CODE.
// H2/H1-BEAT-H4 SUPPRESSION LIVE IN applySuppression. NOT HERE.
// ========================================================================
static void runH4(FSContext &Ctx) {
  std::map<std::string, StructType *> arrayStructs;
  for (Function *F : sortedThreadFns(Ctx)) {
    if (F->isDeclaration())
      continue;
    for (BasicBlock &BB : *F) {
      for (Instruction &I : BB) {
        auto *GEP = dyn_cast<GetElementPtrInst>(&I);
        if (!GEP)
          continue;
        GepInfo gi = analyzeGep(cast<GEPOperator>(GEP));
        if (gi.structTy && gi.variableArrayIndex && hasStoreThrough(GEP))
          arrayStructs[structKey(gi.structTy)] = gi.structTy;
      }
    }
  }

  for (auto &kv : arrayStructs) {
    const std::string &key = kv.first;
    StructType *st = kv.second;
    uint64_t sz = Ctx.DL.getStructLayout(st)->getSizeInBytes();
    if (sz % CACHE_LINE_BYTES == 0)
      continue; // NICE MULTIPLE. NO STRADDLE.
    uint64_t align = Ctx.DL.getABITypeAlign(st).value();
    if (align >= CACHE_LINE_BYTES)
      continue; // ALREADY LINE ALIGNED. FINE.

    Finding f;
    f.heuristic = "H4";
    f.severity = "LOW";
    f.structName = key;
    f.structSizeBytes = (int64_t)sz;
    f.hasEPL = false;
    f.hasThreadFn = false;
    f.detail = formatv(
        "{0} (size={1}B) is used as array element but {1} % {2} = {3}. "
        "Array elements straddle cache-line boundaries.",
        key, sz, CACHE_LINE_BYTES, sz % CACHE_LINE_BYTES).str();
    f.fix = formatv("Pad {0} to a multiple of {1} bytes.", key,
                    CACHE_LINE_BYTES).str();
    Ctx.findings.push_back(std::move(f));
  }
}

// ========================================================================
// HEURISTIC H5 (MEDIUM) -- TWO DISTINCT SMALL NON-CONST GLOBAL, EACH WRITTEN
// FROM DIFFERENT THREAD-REACHABLE FUNCTION. GLOBAL MAY LAND NEAR EACH OTHER
// IN DATA SEGMENT -> PLACEMENT-DEPENDENT FALSE SHARING. USE "@name" AS STRUCT.
// ========================================================================
static void runH5(FSContext &Ctx) {
  // GLOBAL -> SET OF THREAD FN NAME THAT WRITE IT.
  std::map<GlobalVariable *, std::set<std::string>> writers;

  for (Function *F : sortedThreadFns(Ctx)) {
    if (F->isDeclaration())
      continue;
    for (BasicBlock &BB : *F) {
      for (Instruction &I : BB) {
        auto *SI = dyn_cast<StoreInst>(&I);
        if (!SI)
          continue;
        // FOLLOW POINTER TO ROOT OBJECT. GEP / CAST STRIPPED.
        Value *obj = getUnderlyingObject(SI->getPointerOperand());
        auto *GV = dyn_cast<GlobalVariable>(obj);
        if (!GV || GV->isConstant() || !GV->hasInitializer())
          continue;
        uint64_t sz = Ctx.DL.getTypeAllocSize(GV->getValueType());
        if (sz >= CACHE_LINE_BYTES)
          continue; // BIG GLOBAL FILL OWN LINE. LESS RISK.
        writers[GV].insert(F->getName().str());
      }
    }
  }

  // COLLECT SMALL WRITTEN GLOBAL. SORT BY NAME FOR STABLE PAIRING.
  std::vector<GlobalVariable *> gs;
  for (auto &kv : writers)
    gs.push_back(kv.first);
  std::sort(gs.begin(), gs.end(), [](GlobalVariable *a, GlobalVariable *b) {
    return a->getName() < b->getName();
  });

  // PAIR EACH TWO DISTINCT GLOBAL WHERE WRITER FUNCTION DIFFER.
  for (size_t i = 0; i < gs.size(); ++i) {
    for (size_t j = i + 1; j < gs.size(); ++j) {
      GlobalVariable *A = gs[i];
      GlobalVariable *B = gs[j];
      // NEED A WRITER OF A DIFFERENT FROM A WRITER OF B.
      bool differentFns = false;
      for (const std::string &fa : writers[A])
        for (const std::string &fb : writers[B])
          if (fa != fb)
            differentFns = true;
      if (!differentFns)
        continue;

      std::string nameA = ("@" + A->getName()).str();
      std::string nameB = ("@" + B->getName()).str();
      uint64_t szA = Ctx.DL.getTypeAllocSize(A->getValueType());

      std::set<std::string> allFns;
      for (const std::string &fn : writers[A])
        allFns.insert(fn);
      for (const std::string &fn : writers[B])
        allFns.insert(fn);
      std::string fnList;
      for (const std::string &fn : allFns) {
        if (!fnList.empty())
          fnList += ", ";
        fnList += fn;
      }

      Finding f;
      f.heuristic = "H5";
      f.severity = "MEDIUM";
      f.structName = nameA + ", " + nameB;
      f.structSizeBytes = (int64_t)szA;
      f.hasEPL = false;
      f.hasThreadFn = true;
      f.threadFn = fnList;
      f.detail = formatv(
          "Globals {0} (size {1}B) and {2} are each smaller than {3}B and "
          "are written from different thread-reachable functions ({4}). If the "
          "linker places them in the same cache line, concurrent writes cause "
          "placement-dependent false sharing.",
          nameA, szA, nameB, CACHE_LINE_BYTES, fnList).str();
      f.fix = formatv(
          "Separate {0} and {1} onto distinct cache lines "
          "(alignas(64) on each, or group thread-private state).",
          nameA, nameB).str();
      Ctx.findings.push_back(std::move(f));
    }
  }
}

// ========================================================================
// HEURISTIC H6 (MEDIUM) -- VARIABLE-INDEX STORE INTO SHARED SCALAR ARRAY.
// NO STRUCT ANYWHERE: int*/double* HEAP ARRAY OR FIXED GLOBAL SCALAR ARRAY
// INDEXED BY THREAD ID. THE DOMINANT HURON-SUITE PATTERN (false.c, locked,
// lockless, lu_ncb -- 4 OF 7 GROUND-TRUTH BUGS). REQUIRES A STORE THROUGH
// THE GEP. STACK-LOCAL AND THREAD-PRIVATE-HEAP BASES ARE ONE-THREAD-ONLY:
// SKIP.
// ========================================================================
static void runH6(FSContext &Ctx) {
  std::set<std::pair<std::string, std::string>> flagged; // (fn, base key)
  for (Function *F : sortedThreadFns(Ctx)) {
    if (F->isDeclaration())
      continue;
    for (BasicBlock &BB : *F) {
      for (Instruction &I : BB) {
        auto *GEP = dyn_cast<GetElementPtrInst>(&I);
        if (!GEP)
          continue;
        Type *src = GEP->getSourceElementType();
        Type *elem = nullptr;
        bool varIdx = false;
        if (src->isIntegerTy() || src->isFloatingPointTy()) {
          // RAW POINTER WALK: gep i32, ptr %p, i64 %var
          elem = src;
          varIdx = !isa<ConstantInt>(GEP->getOperand(1));
        } else if (auto *AT = dyn_cast<ArrayType>(src)) {
          // FIXED ARRAY: gep [8 x i64], ptr @g, i64 0, i64 %var
          Type *et = AT->getElementType();
          if ((et->isIntegerTy() || et->isFloatingPointTy()) &&
              GEP->getNumOperands() >= 3) {
            elem = et;
            varIdx = !isa<ConstantInt>(GEP->getOperand(2));
          }
        }
        if (!elem || !varIdx)
          continue;
        // DERIVED BASE (ring->buf[i]) = SCALAR ARRAY EMBEDDED IN A BIGGER
        // OBJECT. STRUCT HEURISTICS OWN THAT. H6 ONLY FREE-STANDING ARRAYS.
        if (isa<GEPOperator>(GEP->getPointerOperand()->stripPointerCasts()))
          continue;
        if (!hasStoreThrough(GEP))
          continue;
        uint64_t esz = Ctx.DL.getTypeAllocSize(elem);
        if (esz == 0 || esz >= CACHE_LINE_BYTES)
          continue;

        Value *base = resolveBase(GEP->getPointerOperand());
        if (isa<AllocaInst>(base))
          continue; // STACK ARRAY IN THREAD FN. ONE THREAD ONLY.
        if (isThreadPrivateAlloc(base, F))
          continue; // PRIVATE HEAP BLOCK. SAME PRIVACY RULE AS H1.
        std::string baseName;
        if (auto *GV = dyn_cast<GlobalVariable>(base))
          baseName = ("@" + GV->getName()).str();
        else
          baseName = "(pointer)";

        std::string key = baseName + " " + typeToString(elem) + " array";
        std::string fn = F->getName().str();
        if (!flagged.insert({fn, key}).second)
          continue;

        int64_t epl = (int64_t)(CACHE_LINE_BYTES / esz);
        Finding f;
        f.heuristic = "H6";
        f.severity = "MEDIUM";
        f.structName = key;
        f.structSizeBytes = (int64_t)esz;
        f.hasEPL = true;
        f.epl = epl;
        f.hasThreadFn = true;
        f.threadFn = fn;
        f.detail = formatv(
            "Variable-index store into shared scalar array ({0}, element "
            "{1} = {2}B) from thread function '{3}'. {4} elements share each "
            "{5}B cache line; thread-id-indexed writes to adjacent elements "
            "cause line ping-pong.",
            baseName, typeToString(elem), esz, fn, epl,
            CACHE_LINE_BYTES).str();
        f.fix = formatv(
            "Give each thread a {0}B-aligned slot: stride indices by {1}, "
            "use a padded per-thread struct, or allocate with "
            "aligned_alloc({0}, ...).",
            CACHE_LINE_BYTES, epl).str();
        Ctx.findings.push_back(std::move(f));
      }
    }
  }
}

// ========================================================================
// SUPPRESSION POST-FILTER. ONE PLACE FOR ALL "X BEATS Y" POLICY.
// TABLE: H2 SUPPRESS {H1, H4}. H1 SUPPRESS {H4}. H3/H5 NEVER TOUCHED.
// RULE: DROP FINDING IF DOMINATING HEURISTIC ALREADY WARN SAME STRUCT.
// WHY ONE PLACE: SCATTERED INLINE GUARD MISS PAIR (H1 vs H4 WAS MISSED).
// NEW HEURISTIC? ADD ROW TO TABLE. NO HUNT THROUGH runHX BODIES.
// ========================================================================
static void applySuppression(FSContext &Ctx) {
  // TABLE OF DOMINANCE. victim -> LIST OF HEURISTIC THAT SILENCE IT.
  static const std::map<std::string, std::vector<std::string>> suppressedBy = {
      {"H1", {"H2"}},
      {"H4", {"H2", "H1"}},
  };

  // COLLECT WHICH (heuristic, struct) PAIR FIRED. LOOKUP BOWL.
  std::set<std::pair<std::string, std::string>> fired;
  for (const Finding &f : Ctx.findings)
    fired.insert({f.heuristic, f.structName});

  // DROP VICTIM IF ANY DOMINATOR FIRED FOR SAME STRUCT NAME.
  Ctx.findings.erase(
      std::remove_if(Ctx.findings.begin(), Ctx.findings.end(),
                     [&](const Finding &f) {
                       auto it = suppressedBy.find(f.heuristic);
                       if (it == suppressedBy.end())
                         return false; // NOT A VICTIM. KEEP.
                       for (const std::string &dom : it->second)
                         if (fired.count({dom, f.structName}))
                           return true; // DOMINATOR SPOKE. VICTIM QUIET.
                       return false;
                     }),
      Ctx.findings.end());
}

// ------------------------------------------------------------------------
// EMIT JSON. SAME SHAPE AS TIER 1 --json. AGENT AND evaluate.py EAT UNIFORM.
// ------------------------------------------------------------------------
static void emitJson(FSContext &Ctx) {
  json::Object root;
  root["file"] = Ctx.M.getSourceFileName();

  json::Array entries;
  for (const std::string &e : Ctx.threadEntries)
    entries.push_back(e);
  root["thread_entries"] = std::move(entries);

  // THREAD-REACHABLE SORTED BY NAME. MATCH TIER 1.
  std::vector<std::string> reach;
  for (Function *F : Ctx.threadReachable)
    reach.push_back(F->getName().str());
  std::sort(reach.begin(), reach.end());
  json::Array reachArr;
  for (const std::string &r : reach)
    reachArr.push_back(r);
  root["thread_reachable"] = std::move(reachArr);

  // STRUCT LAYOUTS. EVERY NAMED %struct.X IN MODULE. EXACT DataLayout OFFSET.
  json::Object layouts;
  std::vector<StructType *> structs = Ctx.M.getIdentifiedStructTypes();
  std::sort(structs.begin(), structs.end(), [](StructType *a, StructType *b) {
    return a->getName() < b->getName();
  });
  for (StructType *ST : structs) {
    if (!ST->hasName() || !ST->getName().starts_with("struct."))
      continue;
    if (ST->isOpaque())
      continue;
    const StructLayout *SL = Ctx.DL.getStructLayout(ST);
    json::Object layout;
    layout["size_bytes"] = (int64_t)SL->getSizeInBytes();
    layout["align_bytes"] = (int64_t)Ctx.DL.getABITypeAlign(ST).value();
    json::Array fields;
    for (unsigned i = 0; i < ST->getNumElements(); ++i) {
      Type *ft = ST->getElementType(i);
      json::Object field;
      field["index"] = (int64_t)i;
      field["type"] = typeToString(ft);
      field["offset"] = (int64_t)SL->getElementOffset(i);
      field["size"] = (int64_t)Ctx.DL.getTypeAllocSize(ft);
      field["unknown"] = false;
      fields.push_back(std::move(field));
    }
    layout["fields"] = std::move(fields);
    layouts[structKey(ST)] = std::move(layout);
  }
  root["struct_layouts"] = std::move(layouts);

  // FINDINGS. DETERMINISTIC ORDER: SEVERITY THEN STRUCT NAME.
  std::sort(Ctx.findings.begin(), Ctx.findings.end(),
            [](const Finding &a, const Finding &b) {
              int ra = sevRank(a.severity), rb = sevRank(b.severity);
              if (ra != rb)
                return ra < rb;
              if (a.structName != b.structName)
                return a.structName < b.structName;
              return a.heuristic < b.heuristic;
            });

  json::Array findings;
  for (const Finding &f : Ctx.findings) {
    json::Object o;
    o["heuristic"] = f.heuristic;
    o["severity"] = f.severity;
    o["struct"] = f.structName;
    o["struct_size_bytes"] = f.structSizeBytes;
    if (f.hasEPL)
      o["elements_per_cache_line"] = f.epl;
    else
      o["elements_per_cache_line"] = nullptr;
    if (f.hasThreadFn)
      o["thread_fn"] = f.threadFn;
    else
      o["thread_fn"] = nullptr;
    o["detail"] = f.detail;
    o["fix"] = f.fix;
    findings.push_back(std::move(o));
  }
  root["findings"] = std::move(findings);

  // PRETTY PRINT INDENT 2. LIKE TIER 1 json.dumps(indent=2).
  outs() << formatv("{0:2}", json::Value(std::move(root))) << "\n";
}

// ------------------------------------------------------------------------
// THE PASS. MODULE PASS. NEW PASS MANAGER. ANALYSIS ONLY. NO IR CHANGE.
// ------------------------------------------------------------------------
struct FalseSharingPass : PassInfoMixin<FalseSharingPass> {
  PreservedAnalyses run(Module &M, ModuleAnalysisManager &) {
    FSContext Ctx(M);
    discoverThreadReachable(Ctx);

    runH2(Ctx);   // HIGH -- ARRAY OF SMALL STRUCT.
    runH3(Ctx);   // HIGH -- ATOMIC FIELD SAME LINE.
    runH1(Ctx);   // MEDIUM -- TWO FIELD SAME LINE.
    runH5(Ctx);   // MEDIUM -- TWO SMALL GLOBAL.
    runH6(Ctx);   // MEDIUM -- SCALAR ARRAY INDEXED BY THREAD.
    runH4(Ctx);   // LOW  -- STRADDLE ARRAY ELEMENT.

    // ONE SUPPRESSION PASS AFTER ALL HEURISTIC SPEAK. POLICY IN ONE PLACE.
    applySuppression(Ctx);

    emitJson(Ctx);
    return PreservedAnalyses::all(); // LOOK ONLY. TOUCH NOTHING.
  }

  // ALWAYS RUN EVEN IF FUNCTION MARKED optnone ETC.
  static bool isRequired() { return true; }
};

} // end anonymous namespace

// ------------------------------------------------------------------------
// PLUGIN REGISTRATION. opt LOAD .so. PIPELINE NAME "false-sharing".
// ------------------------------------------------------------------------
llvm::PassPluginLibraryInfo getFalseSharingPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "FalseSharingPass", LLVM_VERSION_STRING,
          [](PassBuilder &PB) {
            PB.registerPipelineParsingCallback(
                [](StringRef Name, ModulePassManager &MPM,
                   ArrayRef<PassBuilder::PipelineElement>) {
                  if (Name == "false-sharing") {
                    MPM.addPass(FalseSharingPass());
                    return true;
                  }
                  return false;
                });
          }};
}

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo
llvmGetPassPluginInfo() {
  return getFalseSharingPluginInfo();
}
