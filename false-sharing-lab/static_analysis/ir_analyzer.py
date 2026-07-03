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
    struct_m = re.match(r'^(%struct\.[\w.]+)$', typename)
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
    struct_decl_re = re.compile(r'^(%struct\.[\w.]+)\s*=\s*type\s*\{([^}]*)\}')
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
            nested_m = re.match(r'(%struct\.[\w.]+)', ftype)
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
                        # AVOID DUPLICATE.
                        if (fn_name, entry) not in thread_entries:
                            thread_entries.append((fn_name, entry))

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


def find_gep_accesses(fn_lines):
    """
    Scan function lines for GEP instructions relevant to false-sharing detection.

    Returns:
      variable_index_geps: list of struct names accessed with variable i64 index (H2 signal)
      field_stores:        list of (struct_name, field_idx) pairs for fields written (H1 signal)
    """
    # LOOK FOR TWO GEP PATTERNS:
    #
    # PATTERN 1 (H2 SIGNAL): ARRAY-OF-STRUCT INDEXING. VARIABLE INDEX.
    #   %reg = getelementptr inbounds %struct.X, ptr %base, i64 %var_idx
    #   THE %var_idx MEANS DYNAMIC INDEX. DIFFERENT THREAD USE DIFFERENT INDEX.
    #   IF STRUCT SMALL, ELEMENTS PACK SAME CACHE LINE. VERY BAD.
    #
    # PATTERN 2 (H1 SIGNAL): FIELD ACCESS. CONSTANT INDEX.
    #   %reg = getelementptr inbounds %struct.X, ptr %base, i32 0, i32 N
    #   INDEX N IS FIELD NUMBER. IF TWO FIELD IN SAME 64B BUCKET, H1 FIRE.

    # H2: VARIABLE INDEX GEP. i64 %reg (NOT CONSTANT NUMBER).
    var_idx_gep_re = re.compile(
        r'%(\w+)\s*=\s*getelementptr\s+inbounds\s+(%struct\.[\w.]+),\s*ptr\s+%\w+,\s*i64\s+%(\w+)'
    )

    # H2 SHAPE 2: GLOBAL/STACK FIXED ARRAY OF STRUCTS. GEP SOURCE TYPE IS ARRAY.
    #   %reg = getelementptr inbounds [4 x %struct.X], ptr @g, i64 0, i64 %var
    # CORPUS CASE adv_tp_stats_array TAUGHT THIS SHAPE. LSHAZ FOUND SAME
    # PATTERN IN LLVM TrackingStatistic. ELEMENT MUST BE STRUCT — SCALAR ARRAY
    # ([8 x i64]) IS H6 TERRITORY, NOT H2. BASE CAN BE @GLOBAL OR %REG.
    array_var_idx_gep_re = re.compile(
        r'%(\w+)\s*=\s*getelementptr\s+inbounds\s+\[\d+\s+x\s+(%struct\.[\w.]+)\],'
        r'\s*ptr\s+[@%][\w.]+,\s*i64\s+0,\s*i64\s+%(\w+)'
    )

    # H1: FIELD ACCESS GEP. i32 0, i32 FIELD_IDX (CONSTANT FIELD INDEX).
    field_gep_re = re.compile(
        r'%(\w+)\s*=\s*getelementptr\s+inbounds\s+(%struct\.[\w.]+),\s*ptr\s+%\w+,\s*i32\s+0,\s*i32\s+(\d+)'
    )

    # STORE INSTRUCTION. FIND WRITE TO MEMORY.
    # store TYPE VALUE, ptr %TARGET
    # OPTIONAL volatile TOKEN. CLANG EMIT 'store volatile i64 ...' FOR VOLATILE FIELD.
    # REVIEW FOUND THESE MISSED. VOLATILE FIELD IS EXACTLY THE HOT KIND. MUST SEE.
    store_re = re.compile(r'\bstore\b\s+(?:volatile\s+)?\S+\s+\S+,\s*ptr\s+%(\w+)')

    variable_index_geps = []   # struct names from H2-pattern GEPs
    field_gep_map = {}         # result_reg -> (struct_name, field_idx)
    stored_registers = set()   # registers that got stored to

    for line in fn_lines:
        # CHECK VARIABLE-INDEX GEP. H2 SIGNAL. BOTH SHAPES.
        m = var_idx_gep_re.search(line) or array_var_idx_gep_re.search(line)
        if m:
            struct_name = m.group(2)
            variable_index_geps.append(struct_name)
            continue  # SKIP FURTHER CHECKS ON THIS LINE. ONE GEP PER LINE IN IR.

        # CHECK FIELD-ACCESS GEP. H1 SIGNAL.
        m2 = field_gep_re.search(line)
        if m2:
            result_reg = m2.group(1)
            struct_name = m2.group(2)
            field_idx = int(m2.group(3))
            field_gep_map[result_reg] = (struct_name, field_idx)
            continue

        # CHECK STORE. MARK WRITTEN REGISTERS.
        m3 = store_re.search(line)
        if m3:
            stored_registers.add(m3.group(1))

    # FIND FIELDS THAT GOT STORED TO. CROSS FIELD GEP MAP WITH STORED REGISTERS.
    # IF FIELD GEP RESULT REGISTER APPEARS AS STORE TARGET, THAT FIELD IS WRITTEN.
    field_stores = []
    for reg, (struct_name, field_idx) in field_gep_map.items():
        if reg in stored_registers:
            field_stores.append((struct_name, field_idx))

    return variable_index_geps, field_stores


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
    entry_fn_names = [entry for _, entry in thread_entry_pairs]
    thread_reachable = build_call_closure(entry_fn_names, all_functions)

    findings = []
    h2_flagged_structs = set()     # STRUCTS ALREADY GOT H2. NO DOUBLE FLAG.
    h1_accesses = {}               # struct_name -> [(field_idx, fn_name), ...]
    h4_array_structs = set()       # struct names seen in variable-index GEPs ANYWHERE

    # STEP 4A: SCAN THREAD-REACHABLE FUNCTIONS. H2 AND H1 ONLY MATTER IN THREADS.
    for fn_name in sorted(thread_reachable):
        if fn_name not in all_functions:
            continue
        fn_lines = all_functions[fn_name]
        var_idx_geps, field_stores = find_gep_accesses(fn_lines)

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

    # STEP 5: SUPPRESSION POST-FILTER. POLICY LIVE IN ONE PLACE, NOT SCATTERED GUARDS.
    # STRONGER FINDING FOR SAME STRUCT WIN. WEAKER ONE IS SAME ADVICE, JUST NOISE.
    # H2 BEAT H1 AND H4. H1 BEAT H4. REVIEW FOUND H1+H4 DOUBLE-FIRE ON >64B STRUCT.
    SUPPRESSES = {'H2': {'H1', 'H4'}, 'H1': {'H4'}}
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
    args = parser.parse_args()

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
