#!/usr/bin/env python3
# IR ANALYZER. READ LLVM WORDS. FIND BAD STRUCT. WARN HUMAN.
# NO LLVMLITE. USE REGEX. CAVEMAN TOOLS FOR CAVEMAN JOB.
# LLVM 18 USE OPAQUE POINTER. ptr EVERYWHERE. NOT i64* OR %struct.X*. JUST ptr.
# LEARN NEW LLVM WAY. ADAPT OR DIE.

import re
import sys
import json
import argparse
from pathlib import Path

# CACHE LINE SIZE. UNIVERSAL LAW OF PROCESSOR LAND. 64 BYTES.
# TWO THREAD TOUCH SAME 64 BYTES. LINE BOUNCE BETWEEN CORE. VERY SLOW.
CACHE_LINE_BYTES = 64

# TYPE SIZE TABLE. KNOW HOW BIG EACH LLVM SCALAR TYPE.
# ALIGNMENT = MIN(SIZE, 8) FOR SCALAR. THIS IS SYSV x86-64 ABI RULE.
BASE_TYPE_SIZES = {
    'i1': 1, 'i8': 1, 'i16': 2, 'i32': 4, 'i64': 8, 'i128': 16,
    'ptr': 8,          # OPAQUE POINTER. LLVM 18 WAY. ALWAYS 8 BYTES ON 64-BIT.
    'float': 4,        # SINGLE FLOAT. 4 BYTES.
    'double': 8,       # DOUBLE FLOAT. 8 BYTES.
    'x86_fp80': 16,    # LONG DOUBLE ON X86. WEIRD BUT HANDLE.
    'half': 2,         # HALF PRECISION. RARE BUT EXISTS.
}


def align_up(offset, alignment):
    # ROUND OFFSET UP TO ALIGNMENT. MATH. NOT MAGIC.
    # IF ALIGNMENT ZERO, RETURN OFFSET UNCHANGED.
    if alignment <= 0:
        return offset
    return (offset + alignment - 1) & ~(alignment - 1)


def type_size_and_align(typename, struct_layouts):
    """Return (size_bytes, alignment_bytes) for a given LLVM type string."""
    # CHECK SIMPLE TYPE FIRST. FAST PATH.
    if typename in BASE_TYPE_SIZES:
        size = BASE_TYPE_SIZES[typename]
        return size, min(size, 8)

    # ARRAY TYPE. LOOK LIKE [N x T]. COUNT N ELEMENTS OF TYPE T.
    # EXAMPLE: [56 x i8] = 56 BYTES. [4 x i64] = 32 BYTES.
    arr_m = re.match(r'^\[(\d+)\s+x\s+(.+)\]$', typename)
    if arr_m:
        count = int(arr_m.group(1))
        elem_type = arr_m.group(2).strip()
        elem_size, elem_align = type_size_and_align(elem_type, struct_layouts)
        if elem_size == 0:
            return 0, 1  # UNKNOWN ELEMENT. GIVE UP.
        return count * elem_size, elem_align

    # STRUCT TYPE. LOOK UP IN TABLE ALREADY BUILT.
    struct_m = re.match(r'^(%(?:struct|union)\.[\w.]+)$', typename)
    if struct_m:
        key = struct_m.group(1)
        if key in struct_layouts:
            info = struct_layouts[key]
            return info['size'], info['align']

    # UNKNOWN TYPE. NOT KNOW. RETURN ZERO. CALLER HANDLE.
    return 0, 1


def split_type_list(body):
    """
    Split a comma-separated LLVM type list, respecting nested brackets.
    E.g. "i64, [56 x i8]" -> ["i64", "[56 x i8]"]
    """
    # SPLIT CAREFUL. BRACKET INSIDE BRACKET CONFUSE SIMPLE COMMA SPLIT.
    # DEPTH COUNTER TRACK HOW DEEP INSIDE BRACKET. ONLY SPLIT AT DEPTH ZERO.
    tokens = []
    depth = 0
    current = []
    for ch in body:
        if ch in '([{':
            depth += 1
            current.append(ch)
        elif ch in ')]}':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            tokens.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        tokens.append(''.join(current).strip())
    return [t for t in tokens if t]


def parse_struct_layouts(lines):
    """
    Parse %struct.X = type { ... } declarations from LLVM IR lines.
    Compute field byte offsets and total struct size using natural alignment
    (SysV x86-64 ABI: each field aligned to min(sizeof(field), 8);
    struct size rounded up to max member alignment).
    Returns dict: '%struct.Name' -> {fields: [...], size: int, align: int}
    """
    # COLLECT RAW STRUCT BODIES FIRST. ONE PASS THROUGH FILE.
    # STRUCT DECL ON ONE LINE IN -O0 IR.
    struct_decl_re = re.compile(r'^(%(?:struct|union)\.[\w.]+)\s*=\s*type\s*\{([^}]*)\}')
    raw_structs = {}
    for line in lines:
        m = struct_decl_re.match(line.strip())
        if m:
            raw_structs[m.group(1)] = m.group(2).strip()

    # NOW COMPUTE LAYOUTS. RECURSIVE FOR NESTED STRUCT.
    struct_layouts = {}

    def compute_layout(name, body, depth=0):
        # ALREADY DONE? RETURN FAST.
        if name in struct_layouts:
            return struct_layouts[name]
        # DEPTH GUARD. PREVENT INFINITE LOOP IF STRUCT POINT TO ITSELF. BAD C CODE.
        if depth > 10:
            return None

        field_types = split_type_list(body)
        offset = 0
        max_align = 1
        fields = []

        for i, ftype in enumerate(field_types):
            # NESTED STRUCT? COMPUTE ITS LAYOUT FIRST.
            nested_m = re.match(r'(%(?:struct|union)\.[\w.]+)', ftype)
            if nested_m:
                nested_name = nested_m.group(1)
                if nested_name in raw_structs and nested_name not in struct_layouts:
                    compute_layout(nested_name, raw_structs[nested_name], depth + 1)

            fsize, falign = type_size_and_align(ftype, struct_layouts)

            if fsize == 0:
                # UNKNOWN TYPE. MARK AND SKIP. NO CRASH.
                fields.append({
                    'index': i, 'type': ftype,
                    'offset': offset, 'size': 0, 'unknown': True,
                })
                continue

            # ALIGN OFFSET TO THIS FIELD ALIGNMENT. C ABI RULE.
            offset = align_up(offset, falign)
            fields.append({
                'index': i, 'type': ftype,
                'offset': offset, 'size': fsize, 'unknown': False,
            })
            offset += fsize
            max_align = max(max_align, falign)

        # TOTAL SIZE ROUND UP TO MAX MEMBER ALIGNMENT.
        # EXAMPLE: { i64, i8 } = 16 BYTES NOT 9. ALIGNMENT WASTE SPACE.
        total_size = align_up(offset, max_align)
        struct_layouts[name] = {
            'fields': fields,
            'size': total_size,
            'align': max_align,
        }
        return struct_layouts[name]

    for name, body in raw_structs.items():
        compute_layout(name, body)

    return struct_layouts


def parse_functions(lines):
    """
    Parse LLVM IR into dict: function_name -> [instruction_lines].
    Also extract thread entry functions from pthread_create calls.
    Returns (functions_dict, [(caller_fn, entry_fn), ...])
    """
    # WALK FILE. FIND DEFINE. COLLECT LINES UNTIL CLOSE BRACE.
    # BRACE DEPTH TRACK WHERE FUNCTION ENDS. SIMPLE STATE MACHINE.
    functions = {}
    thread_entries = []

    current_fn = None
    current_lines = []
    brace_depth = 0

    # MATCH: define [attrs] TYPE @name(params) [attrs] {
    fn_def_re = re.compile(r'^define\s+.*?@(\w+)\s*\(')

    for line in lines:
        stripped = line.strip()

        if fn_def_re.match(stripped):
            # NEW FUNCTION START.
            m = fn_def_re.match(stripped)
            current_fn = m.group(1)
            current_lines = [stripped]
            brace_depth = stripped.count('{') - stripped.count('}')
            continue

        if current_fn is not None:
            current_lines.append(stripped)
            brace_depth += stripped.count('{') - stripped.count('}')
            if brace_depth <= 0:
                # FUNCTION DONE. SAVE.
                functions[current_fn] = current_lines
                current_fn = None
                current_lines = []
                brace_depth = 0

    # SCAN ALL FUNCTION BODIES FOR PTHREAD_CREATE CALLS.
    # PTHREAD_CREATE THIRD ARG IS THREAD ENTRY FUNCTION. VERY IMPORTANT.
    # LINE LOOK LIKE: call i32 @pthread_create(ptr %a, ptr null, ptr @entry_fn, ptr %arg)
    pthread_re = re.compile(r'call\s+i32\s+@pthread_create\s*\(([^)]+)\)')

    for fn_name, fn_lines in functions.items():
        for line in fn_lines:
            m = pthread_re.search(line)
            if m:
                # SAME BRACKET-DEPTH SPLIT AS TYPE LISTS. ONE HELPER. NO TWIN CODE.
                args = split_type_list(m.group(1))
                if len(args) >= 3:
                    # THIRD ARG (INDEX 2). EXTRACT @function_name.
                    third = args[2].strip()
                    fn_ref = re.search(r'@(\w+)', third)
                    if fn_ref:
                        entry = fn_ref.group(1)
                        # FOURTH ARG (INDEX 3) = THREAD ARG POINTER. H7 NEED
                        # IT TO SEE &args[i] HANDED TO EACH THREAD.
                        arg_reg = None
                        if len(args) >= 4:
                            arg_m = re.search(r'%(\w+)', args[3])
                            if arg_m:
                                arg_reg = arg_m.group(1)
                        # AVOID DUPLICATE.
                        if all((fn_name, entry) != (c, e)
                               for c, e, _ in thread_entries):
                            thread_entries.append((fn_name, entry, arg_reg))

    return functions, thread_entries


def build_call_closure(start_fns, all_functions):
    """
    Transitively follow call edges from start_fns to find all reachable functions.
    This is the call graph. Not perfect (no function pointers). Good enough for POC.
    """
    # FOLLOW CALLS LIKE HUNTING. START AT THREAD ENTRY. CHASE EVERY CALL.
    # STOP WHEN NO NEW FUNCTION FOUND. BFS STYLE.
    call_re = re.compile(r'\bcall\b.*?@(\w+)\s*\(')
    reachable = set(start_fns)
    queue = list(start_fns)

    while queue:
        fn = queue.pop()
        if fn not in all_functions:
            continue
        for line in all_functions[fn]:
            for m in call_re.finditer(line):
                callee = m.group(1)
                # SKIP LLVM INTRINSICS. THEY START WITH llvm. NOT CARE.
                if callee.startswith('llvm'):
                    continue
                if callee not in reachable and callee in all_functions:
                    reachable.add(callee)
                    queue.append(callee)

    return reachable


# SCALAR LLVM TYPES FOR H6. ARRAY ELEMENT WITH NO STRUCT ANYWHERE.
# DERIVED FROM BASE_TYPE_SIZES SO THE TWO LISTS CANNOT DRIFT. ptr EXCLUDED:
# POINTER TABLES ARE A DIFFERENT BEAST. LONGEST-FIRST SO i128 BEATS i12+8.
SCALAR_TYPES_RE = '(?:' + '|'.join(
    sorted((t for t in BASE_TYPE_SIZES if t != 'ptr'), key=len, reverse=True)
) + ')'


def find_gep_accesses(fn_lines, private_params=frozenset()):
    """
    Scan function lines for GEP instructions relevant to false-sharing detection.

    private_params: register names of pointer parameters proven thread-private
    at every call site (interprocedural privacy seeds).

    Returns:
      variable_index_geps: struct names var-indexed AND written through (H2/H4 signal)
      field_stores:        (struct_name, field_idx) written, non-private base (H1 signal)
      scalar_writes:       (elem_type, base_token) var-indexed scalar stores (H6 signal)
      var_geps:            raw result_reg -> (struct_name, base) map (H7 consumes)
      private:             final set of thread-private pointer registers
    """
    # GEP SHAPES HUNTED HERE:
    #
    # H2 SHAPE 1 (MALLOC POINTER): gep %struct.X, ptr %base, i64 %var
    # H2 SHAPE 2 (FIXED ARRAY):    gep [4 x %struct.X], ptr @g, i64 0, i64 %var
    # H1 (FIELD ACCESS):           gep %struct.X, ptr %base, i32 0, i32 N
    # H6 SHAPE 1 (RAW POINTER):    gep i32, ptr %base, i64 %var
    # H6 SHAPE 2 (FIXED ARRAY):    gep [8 x i64], ptr @g, i64 0, i64 %var
    #
    # HURON ROUND LESSON: FIRING ON THE GEP ALONE OVER-WARNS. READ-ONLY
    # SHARING IS FREE. EVERY VAR-INDEX SIGNAL NOW REQUIRES A STORE THROUGH
    # THE GEP CHAIN (DIRECT, VIA FIELD GEP, OR VIA POINTER SAVED TO A LOCAL
    # SLOT AND RELOADED).

    var_idx_gep_re = re.compile(
        r'%(\w+)\s*=\s*getelementptr\s+inbounds\s+(%(?:struct|union)\.[\w.]+),\s*ptr\s+([%@][\w.]+),\s*i64\s+%(\w+)'
    )
    array_var_idx_gep_re = re.compile(
        r'%(\w+)\s*=\s*getelementptr\s+inbounds\s+\[\d+\s+x\s+(%(?:struct|union)\.[\w.]+)\],'
        r'\s*ptr\s+([%@][\w.]+),\s*i64\s+0,\s*i64\s+%(\w+)'
    )
    field_gep_re = re.compile(
        r'%(\w+)\s*=\s*getelementptr\s+inbounds\s+(%(?:struct|union)\.[\w.]+),\s*ptr\s+%(\w+),\s*i32\s+0,\s*i32\s+(\d+)'
    )
    scalar_var_gep_re = re.compile(
        r'%(\w+)\s*=\s*getelementptr\s+inbounds\s+(' + SCALAR_TYPES_RE + r'),'
        r'\s*ptr\s+([%@][\w.]+),\s*i64\s+%\w+'
    )
    scalar_array_gep_re = re.compile(
        r'%(\w+)\s*=\s*getelementptr\s+inbounds\s+\[\d+\s+x\s+(' + SCALAR_TYPES_RE + r')\],'
        r'\s*ptr\s+([%@][\w.]+),\s*i64\s+0,\s*i64\s+%\w+'
    )

    # STORE / LOAD / ALLOC BOOKKEEPING.
    # OPTIONAL volatile TOKEN. CLANG EMIT 'store volatile i64 ...' FOR VOLATILE FIELD.
    # 'store atomic' IS A LEGAL PREFIX TOO (C11 atomic_store). REVIEW CAUGHT IT.
    store_re = re.compile(r'\bstore\b\s+(?:atomic\s+)?(?:volatile\s+)?\S+\s+\S+,\s*ptr\s+%(\w+)')
    # ATOMIC RMW WRITES COUNT FOR THE H2/H6 WRITE REQUIREMENT (stats_array
    # TAUGHT THIS: atomicrmw IS THE ONLY WRITE THERE). BUT NOT FOR H1 --
    # ATOMIC FIELDS BELONG TO H3, SAME SPLIT AS TIER 2.
    atomic_re = re.compile(
        r'\b(?:atomicrmw\s+(?:volatile\s+)?\w+|cmpxchg(?:\s+weak)?(?:\s+volatile)?)\s+ptr\s+%(\w+)'
    )
    # llvm.memset/memcpy/memmove DEST IS A WRITE TOO. memset(&arr[tid],0,n)
    # HAS NO store INSTRUCTION AT ALL.
    mem_intr_re = re.compile(
        r'@llvm\.mem(?:set|cpy|move)[\w.]*\(\s*ptr\s+(?:align\s+\d+\s+)?%(\w+)'
    )
    # LOCK/UNLOCK TOUCH THE LOCK WORD = A WRITE TO THAT FIELD. THIS CLOSES
    # THE OPAQUE-CALL GAP FOR THE MUTEX+DATA-SAME-LINE PATTERN (GEMINI
    # ROADMAP PHASE 4: SYNCHRONIZATION MODELING).
    lock_re = re.compile(
        r'@pthread_(?:mutex_(?:lock|unlock|trylock)|spin_(?:lock|unlock|trylock)'
        r'|rwlock_(?:rdlock|wrlock|unlock|trywrlock|tryrdlock))'
        r'\(\s*ptr\s+(?:noundef\s+)?%(\w+)'
    )
    any_gep_re = re.compile(r'%(\w+)\s*=\s*getelementptr\b')
    ptr_store_re = re.compile(r'\bstore\b\s+(?:volatile\s+)?ptr\s+(%\w+|@[\w.]+),\s*ptr\s+([%@][\w.]+)')
    ptr_load_re = re.compile(r'%(\w+)\s*=\s*load\s+ptr,\s*ptr\s+([%@][\w.]+)')
    malloc_re = re.compile(r'%(\w+)\s*=\s*call\s+[^@]*ptr\s+@(?:malloc|calloc|aligned_alloc|realloc)\s*\(')
    ret_ptr_re = re.compile(r'\bret\s+ptr\s+%(\w+)')

    var_geps = {}       # result_reg -> (struct_name, base_token)
    field_gep_map = {}  # result_reg -> (struct_name, field_idx, base_reg)
    scalar_geps = {}    # result_reg -> (elem_type, base_token)
    all_gep_regs = set()
    stored_registers = set()
    atomic_targets = set()
    mem_targets = set()
    lock_targets = set()
    ptr_stores = []     # (value_token, target_token)
    ptr_loads = []      # (result_reg, slot_token)
    malloc_regs = set()
    ret_regs = set()
    pthread_lines = []

    for line in fn_lines:
        mG = any_gep_re.search(line)
        if mG:
            all_gep_regs.add(mG.group(1))
        m = var_idx_gep_re.search(line) or array_var_idx_gep_re.search(line)
        if m:
            var_geps[m.group(1)] = (m.group(2), m.group(3))
            continue
        m2 = field_gep_re.search(line)
        if m2:
            field_gep_map[m2.group(1)] = (m2.group(2), int(m2.group(4)), m2.group(3))
            continue
        m6 = scalar_var_gep_re.search(line) or scalar_array_gep_re.search(line)
        if m6:
            scalar_geps[m6.group(1)] = (m6.group(2), m6.group(3))
            continue
        if mG:
            continue
        if '@pthread_create' in line:
            pthread_lines.append(line)
        mK = lock_re.search(line)
        if mK:
            lock_targets.add(mK.group(1))
            continue
        mI = mem_intr_re.search(line)
        if mI:
            mem_targets.add(mI.group(1))
            continue
        mM = malloc_re.search(line)
        if mM:
            malloc_regs.add(mM.group(1))
            continue
        mR = ret_ptr_re.search(line)
        if mR:
            ret_regs.add(mR.group(1))
        mP = ptr_store_re.search(line)
        if mP:
            ptr_stores.append((mP.group(1), mP.group(2)))
        m3 = store_re.search(line)
        if m3:
            stored_registers.add(m3.group(1))
        mA = atomic_re.search(line)
        if mA:
            atomic_targets.add(mA.group(1))
        mL = ptr_load_re.search(line)
        if mL:
            ptr_loads.append((mL.group(1), mL.group(2)))

    # ANY GEP RESULT COUNTS FOR SLOT LEGALITY, NOT JUST THE TRACKED SHAPES.
    # REVIEW CAUGHT: store INTO AN UNTRACKED GEP (ptr TABLE SLOT) LOOKED
    # LIKE A PLAIN LOCAL SLOT AND KEPT THE POINTER "PRIVATE".
    gep_result_regs = all_gep_regs

    def is_plain_slot(tok):
        return not tok.startswith('@') and tok.lstrip('%') not in gep_result_regs

    loads_by_slot = {}
    for res, slot in ptr_loads:
        loads_by_slot.setdefault(slot, []).append(res)
    vals_by_slot = {}
    for val, slot in ptr_stores:
        if is_plain_slot(slot) and val.startswith('%'):
            vals_by_slot.setdefault(slot, []).append(val.lstrip('%'))

    # POINTER-VALUE FLOW EDGES. -O0 PARKS POINTERS IN ALLOCA SLOTS:
    # store ptr %v, ptr %slot ... %w = load ptr, ptr %slot  =>  %v FLOWS TO %w.
    flow = {}
    for slot, vals in vals_by_slot.items():
        for v in vals:
            flow.setdefault(v, set()).update(loads_by_slot.get(slot, ()))

    write_targets = stored_registers | atomic_targets | mem_targets | lock_targets

    # DERIVED-POINTER ADJACENCY BUILT ONCE. BFS IS O(EDGES), NOT O(GEPS^2).
    children = {}
    for fres, (_, _, fbase) in field_gep_map.items():
        children.setdefault(fbase, []).append(fres)
    for sres, (_, sbase) in scalar_geps.items():
        if sbase.startswith('%'):
            children.setdefault(sbase.lstrip('%'), []).append(sres)
    for v, outs in flow.items():
        children.setdefault(v, []).extend(outs)

    def written_through(root_reg):
        # BFS: ROOT GEP -> DERIVED GEPS -> SLOT-RELOADED COPIES.
        # TRUE IF ANY NODE IS A STORE / ATOMIC / MEM-INTRINSIC TARGET.
        seen = set()
        queue = [root_reg]
        while queue:
            r = queue.pop()
            if r in seen:
                continue
            seen.add(r)
            if r in write_targets:
                return True
            queue.extend(children.get(r, ()))
        return False

    # INSTANCE PRIVACY (HURON lu_ncb LocalCopies LESSON): POINTER BORN FROM
    # malloc IN THIS FUNCTION, NEVER STORED OUTSIDE LOCAL SLOTS, NEVER GIVEN
    # TO pthread_create, NEVER RETURNED => ONE THREAD OWNS IT. NOT SHARED.
    # OTHER DIRECT CALLS (free, HELPERS) RUN ON THE SAME THREAD: NOT ESCAPE.
    private = set(malloc_regs) | set(private_params)
    while True:
        grown = set(private)
        for slot, vals in vals_by_slot.items():
            if vals and all(v in private for v in vals):
                grown.update(loads_by_slot.get(slot, ()))
        if grown == private:
            break
        private = grown

    # ESCAPE IS PER ALIAS GROUP, NOT A WHOLESALE WIPE. REVIEW CAUGHT: ONE
    # RETURNED malloc MUST NOT UN-PRIVATIZE AN UNRELATED SCRATCH malloc.
    escape_seeds = set(ret_regs & private)
    for val, slot in ptr_stores:
        v = val.lstrip('%')
        if v in private and not is_plain_slot(slot):
            escape_seeds.add(v)
    for line in pthread_lines:
        # TOKEN-BOUNDARY MATCH. SUBSTRING '%1' IN '%10' BURNED US.
        for p in private:
            if re.search(r'%' + re.escape(p) + r'\b', line):
                escape_seeds.add(p)
    # CLOSURE OVER SLOT ALIASING: ESCAPED VALUE TAINTS ITS RELOADS AND
    # SLOT-MATES. OVERAPPROXIMATE = CONSERVATIVE (LESS PRIVACY, NEVER MORE).
    tainted = set()
    queue = list(escape_seeds)
    while queue:
        r = queue.pop()
        if r in tainted:
            continue
        tainted.add(r)
        for slot, vals in vals_by_slot.items():
            if r in vals:
                queue.extend(vals)
                queue.extend(loads_by_slot.get(slot, ()))
        for res, slot in ptr_loads:
            if res == r:
                queue.extend(vals_by_slot.get(slot, ()))
                queue.extend(loads_by_slot.get(slot, ()))
    private -= tainted

    variable_index_geps = [
        s for reg, (s, base) in var_geps.items()
        if written_through(reg) and base.lstrip('%') not in private
    ]
    # LOCK CALLS COUNT AS FIELD WRITES FOR H1 (LOCK WORD LIVES IN THE FIELD).
    # ATOMICS STAY OUT: THOSE ARE H3'S.
    field_stores = [
        (s, fi) for reg, (s, fi, base) in field_gep_map.items()
        if (reg in stored_registers or reg in lock_targets) and base not in private
    ]
    # H6 ONLY OWNS FREE-STANDING SCALAR ARRAYS. BASE THAT IS ITSELF A GEP
    # RESULT = ARRAY EMBEDDED IN A BIGGER OBJECT (ring->buf[i]) = STRUCT
    # HEURISTIC TERRITORY. ring_head_tail TAUGHT THIS.
    scalar_writes = [
        (elem, base) for reg, (elem, base) in scalar_geps.items()
        if written_through(reg)
        and base.lstrip('%') not in private
        and base.lstrip('%') not in gep_result_regs
    ]

    return variable_index_geps, field_stores, scalar_writes, var_geps, private


def analyze(ll_path):
    """
    Main analysis entry point.
    Parses the .ll file, applies H2/H1/H4 heuristics, returns findings list.
    """
    # READ WHOLE FILE. ALL LINES. KEEP NEWLINES FOR LINE-ORIENTED PARSING.
    with open(ll_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # STEP 1: PARSE STRUCT LAYOUTS. LEARN SHAPE OF DATA.
    struct_layouts = parse_struct_layouts(lines)

    # STEP 2: PARSE FUNCTION BODIES. ALSO FIND THREAD ENTRIES FROM PTHREAD_CREATE.
    all_functions, thread_entry_pairs = parse_functions(lines)

    # STEP 3: BUILD THREAD-REACHABLE CLOSURE. START FROM THREAD ENTRIES.
    # FOLLOW CALLS TRANSITIVELY. THESE FUNCTION TOUCH SHARED DATA.
    entry_fn_names = [entry for _, entry, _ in thread_entry_pairs]
    thread_reachable = build_call_closure(entry_fn_names, all_functions)

    # STEP 3B: INTERPROCEDURAL PRIVATE-PARAM PROPAGATION (lu_ncb LocalCopies
    # LESSON): PRIVATE malloc POINTER PASSED DOWN TO A HELPER MUST STAY
    # PRIVATE THERE. FIXPOINT: CALLEE PARAM IS PRIVATE IFF EVERY CALL SITE
    # PASSES A PRIVATE VALUE AND THE CALLEE'S ADDRESS IS NEVER TAKEN.
    param_re = re.compile(r'^define\s+[^(]*@\w+\s*\(([^)]*)\)')
    call_site_re = re.compile(r'\bcall\b[^@]*@(\w+)\((.*)\)')
    arg_reg_re = re.compile(r'%([\w.]+)\s*$')
    fn_params = {}
    for fn, fl in all_functions.items():
        m = param_re.match(fl[0])
        toks = split_type_list(m.group(1)) if m else []
        fn_params[fn] = [
            (arg_reg_re.search(t.strip()).group(1)
             if arg_reg_re.search(t.strip()) else None)
            for t in toks
        ]

    # ADDRESS-TAKEN FUNCTIONS: THREAD ENTRIES, OR NAME PASSED AS AN ARG
    # SOMEWHERE. THEIR PARAMS ARRIVE FROM OUTSIDE THE VISIBLE CALL SITES.
    addr_taken = set(entry_fn_names)
    for fn, fl in all_functions.items():
        for line in fl:
            cm = call_site_re.search(line)
            if not cm:
                continue
            for tok in split_type_list(cm.group(2)):
                am = re.search(r'@(\w+)', tok)
                if am:
                    addr_taken.add(am.group(1))

    private_params = {fn: frozenset() for fn in all_functions}
    facts = {}
    for _ in range(4):
        for fn, fl in all_functions.items():
            facts[fn] = find_gep_accesses(fl, private_params[fn])
        votes = {}
        for fn, fl in all_functions.items():
            priv = facts[fn][4]
            for line in fl:
                cm = call_site_re.search(line)
                if not cm or cm.group(1) not in all_functions:
                    continue
                callee = cm.group(1)
                for k, tok in enumerate(split_type_list(cm.group(2))):
                    rm = arg_reg_re.search(tok.strip())
                    is_priv = bool(rm) and rm.group(1) in priv
                    ok, n = votes.get((callee, k), (True, 0))
                    votes[(callee, k)] = (ok and is_priv, n + 1)
        new_map = {fn: set() for fn in all_functions}
        for (callee, k), (ok, n) in votes.items():
            if ok and n > 0 and callee not in addr_taken:
                params = fn_params.get(callee, [])
                if k < len(params) and params[k]:
                    new_map[callee].add(params[k])
        new_map = {fn: frozenset(v) for fn, v in new_map.items()}
        if new_map == private_params:
            break
        private_params = new_map

    findings = []
    h2_flagged_structs = set()     # STRUCTS ALREADY GOT H2. NO DOUBLE FLAG.
    h1_accesses = {}               # struct_name -> [(field_idx, fn_name), ...]
    h4_array_structs = set()       # struct names seen in variable-index GEPs ANYWHERE
    h6_flagged = set()             # (base, elem) ALREADY GOT H6.

    # STEP 4A: SCAN THREAD-REACHABLE FUNCTIONS. H2 AND H1 ONLY MATTER IN THREADS.
    for fn_name in sorted(thread_reachable):
        if fn_name not in all_functions:
            continue
        var_idx_geps, field_stores, scalar_writes, _, _ = facts[fn_name]

        # H6 CHECK: VARIABLE-INDEX STORE INTO SHARED SCALAR ARRAY. NO STRUCT.
        # THE DOMINANT HURON-SUITE PATTERN (false.c, locked, lockless, lu_ncb).
        # ELEMENT ALWAYS < 64B, SO ADJACENT THREAD SLOTS SHARE A LINE.
        for elem_type, base in scalar_writes:
            elem_size = BASE_TYPE_SIZES.get(elem_type, 0)
            if elem_size <= 0:
                continue
            base_label = base if base.startswith('@') else '(pointer)'
            # KEY INCLUDES fn: TWO THREAD FNS HAMMERING ARRAYS BOTH REPORT.
            # SAME DEDUP SHAPE AS TIER 2. REVIEW CAUGHT THE DIVERGENCE.
            key = (fn_name, base_label, elem_type)
            if key in h6_flagged:
                continue
            h6_flagged.add(key)
            epl = CACHE_LINE_BYTES // elem_size
            findings.append({
                'heuristic': 'H6',
                'severity': 'MEDIUM',
                'struct': f'{base_label} {elem_type} array',
                'struct_size_bytes': elem_size,
                'elements_per_cache_line': epl,
                'thread_fn': fn_name,
                'detail': (
                    f"Variable-index store into shared scalar array "
                    f"({base_label}, element {elem_type} = {elem_size}B) from "
                    f"thread function '{fn_name}'. {epl} elements share each "
                    f"{CACHE_LINE_BYTES}B cache line; thread-id-indexed writes "
                    f"to adjacent elements cause line ping-pong."
                ),
                'fix': (
                    f"Give each thread a {CACHE_LINE_BYTES}B-aligned slot: stride "
                    f"indices by {epl}, use a padded per-thread struct, or "
                    f"allocate with aligned_alloc({CACHE_LINE_BYTES}, ...)."
                ),
            })

        # H2 CHECK: VARIABLE-INDEX GEP INTO STRUCT SMALLER THAN CACHE LINE.
        # CLASSIC FALSE SHARING. DIFFERENT THREAD WRITE ADJACENT ELEMENT. SAME LINE.
        # EXAMPLE: counters[tid].value++ WITH tid-INDEXED ARRAY OF 8-BYTE STRUCT.
        for struct_name in var_idx_geps:
            h4_array_structs.add(struct_name)  # ALSO MARK FOR H4 LATER.
            if struct_name not in struct_layouts:
                continue
            layout = struct_layouts[struct_name]
            sz = layout['size']
            if sz < CACHE_LINE_BYTES:
                if struct_name not in h2_flagged_structs:
                    h2_flagged_structs.add(struct_name)
                    # HOW MANY ELEMENTS FIT IN ONE CACHE LINE?
                    elements_per_line = CACHE_LINE_BYTES // sz if sz > 0 else 1
                    findings.append({
                        'heuristic': 'H2',
                        'severity': 'HIGH',
                        'struct': struct_name,
                        'struct_size_bytes': sz,
                        'elements_per_cache_line': elements_per_line,
                        'thread_fn': fn_name,
                        'detail': (
                            f"Variable-index array access into {struct_name} "
                            f"(size={sz}B < {CACHE_LINE_BYTES}B). "
                            f"Function '{fn_name}' indexes array of {struct_name} "
                            f"by thread id -- adjacent elements ({elements_per_line} fit per "
                            f"{CACHE_LINE_BYTES}B cache line) share a cache line. "
                            f"Concurrent writes from different threads cause line ping-pong."
                        ),
                        'fix': (
                            f"Pad {struct_name} to {CACHE_LINE_BYTES} bytes: "
                            f"add 'char padding[{CACHE_LINE_BYTES} - sizeof(struct)]' "
                            f"or annotate with '__attribute__((aligned(64)))' / 'alignas(64)'."
                        ),
                    })

        # COLLECT FIELD STORES FOR H1 CHECK BELOW.
        for struct_name, field_idx in field_stores:
            if struct_name not in h1_accesses:
                h1_accesses[struct_name] = []
            h1_accesses[struct_name].append((field_idx, fn_name))

    # STEP 4B: H1 CHECK. TWO FIELDS OF SAME STRUCT IN SAME 64B BUCKET, BOTH STORED.
    # CHECK: IF TWO THREAD WRITE DIFFERENT FIELD BUT SAME CACHE LINE, STILL BAD.
    # THIS HAPPEN WHEN STRUCT HAVE HOT FIELD AND COLD FIELD ON SAME 64B LINE.
    for struct_name, accesses in h1_accesses.items():
        if struct_name not in struct_layouts:
            continue
        layout = struct_layouts[struct_name]
        fields = layout['fields']

        # GROUP FIELD ACCESSES BY CACHE-LINE BUCKET.
        bucket_map = {}  # bucket_id -> [(field_idx, fn_name)]
        for field_idx, fn_name in accesses:
            matching = [f for f in fields if f['index'] == field_idx and not f.get('unknown')]
            if not matching:
                continue
            field_info = matching[0]
            bucket = field_info['offset'] // CACHE_LINE_BYTES
            if bucket not in bucket_map:
                bucket_map[bucket] = []
            bucket_map[bucket].append((field_idx, fn_name))

        for bucket, bucket_list in bucket_map.items():
            unique_fields = sorted(set(fi for fi, _ in bucket_list))
            if len(unique_fields) >= 2:
                fn_names = sorted(set(fn for _, fn in bucket_list))
                findings.append({
                    'heuristic': 'H1',
                    'severity': 'MEDIUM',
                    'struct': struct_name,
                    'struct_size_bytes': layout['size'],
                    'elements_per_cache_line': None,
                    'thread_fn': ', '.join(fn_names),
                    'detail': (
                        f"Fields {unique_fields} of {struct_name} occupy "
                        f"cache-line bucket {bucket} (offset {bucket * CACHE_LINE_BYTES}"
                        f"-{(bucket + 1) * CACHE_LINE_BYTES - 1}B) and are "
                        f"both written from thread-reachable code."
                    ),
                    'fix': (
                        f"Split hot fields of {struct_name} into a separate struct, "
                        f"or insert padding to push fields to different cache lines."
                    ),
                })

    # STEP 4C: EMIT H4 ADVISORY FOR NON-ALIGNED STRUCT SIZES.
    # h4_array_structs ALREADY FILLED BY STEP 4A (THREAD-REACHABLE SCAN ONLY).
    # SINGLE THREAD CANNOT FALSE-SHARE. NO THREAD, NO H4. GUARD LIVE IN 4A.
    for struct_name in sorted(h4_array_structs):
        if struct_name not in struct_layouts:
            continue
        layout = struct_layouts[struct_name]
        sz = layout['size']
        if sz % CACHE_LINE_BYTES != 0:
            findings.append({
                'heuristic': 'H4',
                'severity': 'LOW',
                'struct': struct_name,
                'struct_size_bytes': sz,
                'elements_per_cache_line': None,
                'thread_fn': None,
                'detail': (
                    f"{struct_name} (size={sz}B) is used as array element "
                    f"but {sz} % {CACHE_LINE_BYTES} = {sz % CACHE_LINE_BYTES}. "
                    f"Array elements straddle cache-line boundaries."
                ),
                'fix': (
                    f"Pad {struct_name} to a multiple of {CACHE_LINE_BYTES} bytes."
                ),
            })

    # STEP 4D: H7 -- PTHREAD ARG ARRAY WHOSE ELEMENTS STRADDLE LINE BOUNDARIES.
    # &args[i] HANDED TO EACH THREAD, sizeof(S) >= 64, sizeof % 64 != 0, NO
    # 64B ALIGNMENT => NEIGHBOR ELEMENTS SHARE THE BOUNDARY LINES. THE HURON
    # histogram MECHANISM (3096B thread_arg_t). GEMINI ROADMAP PHASE 1.
    h7_flagged = set()
    for caller, entry, arg_reg in thread_entry_pairs:
        if arg_reg is None or caller not in all_functions:
            continue
        caller_var_geps = facts[caller][3]
        if arg_reg not in caller_var_geps:
            continue
        struct_name, _base = caller_var_geps[arg_reg]
        if struct_name in h7_flagged or struct_name not in struct_layouts:
            continue
        layout = struct_layouts[struct_name]
        sz = layout['size']
        if sz < CACHE_LINE_BYTES or sz % CACHE_LINE_BYTES == 0:
            continue
        if layout['align'] >= CACHE_LINE_BYTES:
            continue
        h7_flagged.add(struct_name)
        findings.append({
            'heuristic': 'H7',
            'severity': 'MEDIUM',
            'struct': struct_name,
            'struct_size_bytes': sz,
            'elements_per_cache_line': None,
            'thread_fn': entry,
            'detail': (
                f"Per-thread arg array of {struct_name} (size={sz}B, "
                f"{sz} % {CACHE_LINE_BYTES} = {sz % CACHE_LINE_BYTES}, "
                f"alignment < {CACHE_LINE_BYTES}B): pthread_create hands "
                f"&args[i] to each thread, so neighbouring elements straddle "
                f"shared cache lines at their boundaries even though each "
                f"thread only touches its own element."
            ),
            'fix': (
                f"Pad {struct_name} to a multiple of {CACHE_LINE_BYTES}B and "
                f"allocate the array with aligned_alloc({CACHE_LINE_BYTES}, ...) "
                f"or alignas({CACHE_LINE_BYTES})."
            ),
        })

    # STEP 5: SUPPRESSION POST-FILTER. POLICY LIVE IN ONE PLACE, NOT SCATTERED GUARDS.
    # STRONGER FINDING FOR SAME STRUCT WIN. WEAKER ONE IS SAME ADVICE, JUST NOISE.
    # H2 BEAT H1 AND H4. H1 BEAT H4. H7 BEAT H4 (SAME STRADDLE ADVICE, MORE
    # CONTEXT). REVIEW FOUND H1+H4 DOUBLE-FIRE ON >64B STRUCT.
    SUPPRESSES = {'H2': {'H1', 'H4'}, 'H1': {'H4'}, 'H7': {'H4'}}
    fired_by = {}  # struct -> set of heuristics that fired
    for f in findings:
        fired_by.setdefault(f['struct'], set()).add(f['heuristic'])
    findings = [
        f for f in findings
        if not any(f['heuristic'] in SUPPRESSES.get(dom, set())
                   for dom in fired_by[f['struct']] if dom != f['heuristic'])
    ]

    return findings, struct_layouts, thread_reachable, entry_fn_names


def format_human(findings, struct_layouts, thread_reachable, entry_fn_names, ll_path):
    """Format findings as a human-readable report string."""
    # WRITE REPORT. HUMAN READ. HUMAN UNDERSTAND. HUMAN FIX CODE.
    lines = []
    lines.append("=" * 70)
    lines.append("FALSE SHARING STATIC ANALYSIS REPORT")
    lines.append("=" * 70)
    lines.append(f"File: {ll_path}")
    lines.append(f"Thread entry functions: {', '.join(entry_fn_names) if entry_fn_names else '(none found)'}")
    lines.append(f"Thread-reachable functions: {', '.join(sorted(thread_reachable)) if thread_reachable else '(none)'}")
    lines.append("")

    # STRUCT LAYOUT SUMMARY.
    lines.append("STRUCT LAYOUTS ANALYZED:")
    for name in sorted(struct_layouts.keys()):
        layout = struct_layouts[name]
        sz = layout['size']
        cl = sz / CACHE_LINE_BYTES
        flag = " *** SIZE < 64B -- ARRAY INDEXING WILL SHARE CACHE LINES ***" if sz < CACHE_LINE_BYTES else ""
        lines.append(f"  {name}: {sz} bytes ({cl:.2f} cache lines){flag}")
        for f in layout['fields']:
            unk = " [UNKNOWN SIZE]" if f.get('unknown') else ""
            lines.append(f"    field[{f['index']}] {f['type']:30s} offset={f['offset']}B  size={f['size']}B{unk}")
    lines.append("")

    # FINDINGS.
    if not findings:
        lines.append("NO FINDINGS. ALL CLEAR.")
    else:
        sev_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        sorted_findings = sorted(findings, key=lambda f: sev_order.get(f['severity'], 9))
        lines.append(f"FINDINGS ({len(findings)} total):")
        lines.append("")
        for i, f in enumerate(sorted_findings, 1):
            sev = f['severity']
            heur = f['heuristic']
            struct = f['struct']
            sz = f['struct_size_bytes']
            fn = f.get('thread_fn') or '(all code)'
            epl = f.get('elements_per_cache_line')

            lines.append(f"  [{sev}] {heur} -- Finding #{i}")
            lines.append(f"    Struct:           {struct}")
            lines.append(f"    Struct size:      {sz} bytes")
            if epl:
                lines.append(f"    Elements/line:    {epl} elements fit in one {CACHE_LINE_BYTES}B cache line")
            lines.append(f"    Offending fn:     {fn}")
            lines.append(f"    Detail:           {f['detail']}")
            lines.append(f"    Suggested fix:    {f['fix']}")
            lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Static false-sharing analyzer for LLVM IR (.ll) files."
    )
    parser.add_argument('ll_file', help="Path to the .ll file to analyze")
    parser.add_argument('--json', action='store_true', help="Output findings as JSON instead of human-readable text")
    parser.add_argument('--line-size', type=int, default=64,
                        help="Cache line size in bytes (default 64; e.g. 128 for Apple M-series L2)")
    args = parser.parse_args()

    # PARAMETRIZED TOPOLOGY (GEMINI ROADMAP PHASE 6). ONE GLOBAL, SET ONCE.
    global CACHE_LINE_BYTES
    CACHE_LINE_BYTES = args.line_size

    ll_path = Path(args.ll_file)
    if not ll_path.exists():
        print(f"ERROR: File not found: {ll_path}", file=sys.stderr)
        sys.exit(1)

    # RUN ANALYSIS. THIS IS THE MAIN EVENT.
    findings, struct_layouts, thread_reachable, entry_fn_names = analyze(ll_path)

    if args.json:
        # JSON OUTPUT FOR AGENT. MACHINE READABLE. SERVE AGENT.
        output = {
            'file': str(ll_path),
            'thread_entries': entry_fn_names,
            'thread_reachable': sorted(thread_reachable),
            'struct_layouts': {
                name: {
                    'size_bytes': info['size'],
                    'align_bytes': info['align'],
                    'fields': info['fields'],
                }
                for name, info in struct_layouts.items()
            },
            'findings': findings,
        }
        print(json.dumps(output, indent=2))
    else:
        # HUMAN READABLE OUTPUT. TALK TO HUMAN.
        print(format_human(findings, struct_layouts, thread_reachable, entry_fn_names, ll_path))


if __name__ == '__main__':
    main()
