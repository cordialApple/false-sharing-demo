#!/usr/bin/env python3
# GROK TIER 2 WRAPPER. SAME CLI AS TIER 1 ir_analyzer.py.
# GROK NOT PARSE IR HERE. GROK CALL REAL LLVM PASS. PASS DO HARD WORK.
# DUAL MODE: WINDOWS HOST -> WSL + PATH TRANSLATE. LINUX CI -> opt DIRECT.
#
# CONTRACT (MATCH TIER 1 EXACT):
#   python tier2_analyzer.py <file.ll> [--json]
#     --json   -> PRINT RAW PASS JSON
#     (no flag)-> RENDER HUMAN REPORT

import re
import sys
import os
import json
import argparse
import subprocess
from pathlib import Path, PureWindowsPath

# CACHE LINE SIZE. UNIVERSAL LAW. 64 BYTE. SAME AS TIER 1.
CACHE_LINE_BYTES = 64

# WHERE PLUGIN LIVE. RELATIVE TO THIS SCRIPT. build.sh MAKE IT.
PLUGIN_REL = Path("tier2_pass") / "build" / "FalseSharingPass.so"

# GROK TRY THESE opt BINARY IN ORDER. apt ALTERNATIVES VARY BY MACHINE.
OPT_CANDIDATES = ["opt-18", "/usr/lib/llvm-18/bin/opt", "opt"]


def win_to_wsl(path: Path) -> str:
    """Convert an absolute Windows path (C:\\a\\b) to a WSL path (/mnt/c/a/b)."""
    # GROK TURN WINDOWS PATH INTO WSL /mnt PATH. DRIVE LETTER GO LOWER CASE.
    abspath = Path(path).resolve()
    win = PureWindowsPath(abspath)
    drive = win.drive.rstrip(":").lower()   # "C:" -> "c"
    parts = win.parts[1:]                    # DROP THE "C:\\" ANCHOR
    tail = "/".join(parts)
    return f"/mnt/{drive}/{tail}"


def find_opt() -> str:
    """Probe for a usable opt binary. On Linux: check PATH directly. On Windows: via WSL."""
    # DUAL MODE. WINDOWS = ASK WSL. LINUX = LOOK IN PATH/KNOWN DIRS DIRECT.
    if os.name != 'nt':
        # LINUX CI. NO WSL. PROBE NATIVE PATH.
        for cand in OPT_CANDIDATES:
            try:
                r = subprocess.run(
                    ['sh', '-c', f'command -v {cand}'],
                    capture_output=True, text=True,
                )
                if r.returncode == 0 and r.stdout.strip():
                    return cand
            except FileNotFoundError:
                continue
        return OPT_CANDIDATES[0]  # FALLBACK. LET RUN FAIL WITH CLEAR MESSAGE.
    else:
        # WINDOWS HOST. ASK WSL WHICH opt WORK. FIRST ONE ANSWER WIN.
        for cand in OPT_CANDIDATES:
            try:
                r = subprocess.run(
                    ["wsl", "-e", "sh", "-c", f"command -v {cand}"],
                    capture_output=True, text=True,
                )
                if r.returncode == 0 and r.stdout.strip():
                    return cand
            except FileNotFoundError:
                # WSL ITSELF MISSING. GROK CANNOT WORK. TELL HUMAN LOUD.
                print("ERROR: 'wsl' not found. Tier 2 needs WSL Ubuntu with LLVM 18.",
                      file=sys.stderr)
                sys.exit(2)
        return OPT_CANDIDATES[0]  # FALLBACK. LET RUN FAIL WITH CLEAR MESSAGE.


def run_pass(ll_path: Path) -> dict:
    """Run the FalseSharingPass on ll_path; return parsed JSON dict."""
    # GROK CHECK PLUGIN EXIST FIRST. NO PLUGIN = NO ANALYSIS. TELL HUMAN HOW BUILD.
    script_dir = Path(__file__).resolve().parent
    plugin_path = script_dir / PLUGIN_REL

    if not plugin_path.exists():
        if os.name == 'nt':
            build_hint = (
                '  wsl -e sh -c "cd '
                f"{win_to_wsl(script_dir / 'tier2_pass')}"
                ' && sh build.sh"'
            )
        else:
            build_hint = f'  cd {script_dir / "tier2_pass"} && sh build.sh'
        print(
            "ERROR: FalseSharingPass.so not found at\n"
            f"  {plugin_path}\n"
            "Build it first:\n"
            f"{build_hint}",
            file=sys.stderr,
        )
        sys.exit(2)

    opt_bin = find_opt()

    if os.name != 'nt':
        # LINUX CI. NATIVE PATHS. RUN opt DIRECT. NO WSL INDIRECTION.
        cmd = (
            f"{opt_bin} -load-pass-plugin='{plugin_path}' "
            f"-passes=false-sharing -disable-output '{ll_path}'"
        )
        proc = subprocess.run(['sh', '-c', cmd], capture_output=True, text=True)
    else:
        # WINDOWS HOST. TRANSLATE PATHS TO WSL /mnt FORM. RUN VIA WSL.
        plugin_wsl = win_to_wsl(plugin_path)
        ll_wsl     = win_to_wsl(ll_path)
        # GROK BUILD opt COMMAND. -disable-output SO opt NOT PRINT MODULE.
        # PASS PRINT JSON TO STDOUT. GROK CATCH STDOUT.
        cmd = (
            f"{opt_bin} -load-pass-plugin='{plugin_wsl}' "
            f"-passes=false-sharing -disable-output '{ll_wsl}'"
        )
        proc = subprocess.run(
            ["wsl", "-e", "sh", "-c", cmd],
            capture_output=True, text=True,
        )

    if proc.returncode != 0:
        print("ERROR: opt failed to run the pass.", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        sys.exit(proc.returncode or 1)

    # GROK PARSE STDOUT AS JSON. IF opt PRINT EXTRA NOISE, GRAB FIRST { ... } BLOCK.
    out = proc.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", out, re.DOTALL)
        if not m:
            print("ERROR: pass produced no JSON. Raw output:", file=sys.stderr)
            print(out, file=sys.stderr)
            print(proc.stderr, file=sys.stderr)
            sys.exit(1)
        return json.loads(m.group(0))


def format_human(data: dict, ll_path: Path) -> str:
    """Render pass JSON as a human-readable report (mirrors Tier-1 layout)."""
    # GROK TALK TO HUMAN. SAME SHAPE REPORT AS TIER 1 SO HUMAN NOT CONFUSED.
    struct_layouts = data.get("struct_layouts", {})
    findings = data.get("findings", [])
    thread_reachable = data.get("thread_reachable", [])
    entry_fn_names = data.get("thread_entries", [])

    lines = []
    lines.append("=" * 70)
    lines.append("FALSE SHARING STATIC ANALYSIS REPORT (Tier 2 -- LLVM pass)")
    lines.append("=" * 70)
    lines.append(f"File: {ll_path}")
    lines.append(f"Source: {data.get('file', '(unknown)')}")
    lines.append(
        "Thread entry functions: "
        + (", ".join(entry_fn_names) if entry_fn_names else "(none found)")
    )
    lines.append(
        "Thread-reachable functions: "
        + (", ".join(sorted(thread_reachable)) if thread_reachable else "(none)")
    )
    lines.append("")

    # STRUCT LAYOUT SUMMARY. EXACT OFFSET FROM DataLayout. NOT GUESS.
    lines.append("STRUCT LAYOUTS ANALYZED:")
    for name in sorted(struct_layouts.keys()):
        layout = struct_layouts[name]
        sz = layout["size_bytes"]
        cl = sz / CACHE_LINE_BYTES
        flag = (
            " *** SIZE < 64B -- ARRAY INDEXING WILL SHARE CACHE LINES ***"
            if sz < CACHE_LINE_BYTES
            else ""
        )
        lines.append(f"  {name}: {sz} bytes ({cl:.2f} cache lines){flag}")
        for f in layout["fields"]:
            unk = " [UNKNOWN SIZE]" if f.get("unknown") else ""
            lines.append(
                f"    field[{f['index']}] {f['type']:30s} "
                f"offset={f['offset']}B  size={f['size']}B{unk}"
            )
    lines.append("")

    # FINDINGS. PASS ALREADY SORT BY SEVERITY THEN STRUCT.
    if not findings:
        lines.append("NO FINDINGS. ALL CLEAR. GROK HAPPY.")
    else:
        lines.append(f"FINDINGS ({len(findings)} total):")
        lines.append("")
        for i, f in enumerate(findings, 1):
            sev = f["severity"]
            heur = f["heuristic"]
            fn = f.get("thread_fn") or "(all code)"
            epl = f.get("elements_per_cache_line")

            lines.append(f"  [{sev}] {heur} -- Finding #{i}")
            lines.append(f"    Struct:           {f['struct']}")
            lines.append(f"    Struct size:      {f['struct_size_bytes']} bytes")
            if epl:
                lines.append(
                    f"    Elements/line:    {epl} elements fit in one "
                    f"{CACHE_LINE_BYTES}B cache line"
                )
            lines.append(f"    Offending fn:     {fn}")
            lines.append(f"    Detail:           {f['detail']}")
            lines.append(f"    Suggested fix:    {f['fix']}")
            lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Tier-2 static false-sharing analyzer: runs a real "
                    "out-of-tree LLVM pass (FalseSharingPass) via opt and "
                    "reports findings. Same CLI as ir_analyzer.py. "
                    "Dual-mode: Windows uses WSL; Linux runs opt natively."
    )
    parser.add_argument("ll_file", help="Path to the .ll file to analyze")
    parser.add_argument(
        "--json", action="store_true",
        help="Output findings as JSON instead of human-readable text",
    )
    args = parser.parse_args()

    ll_path = Path(args.ll_file)
    if not ll_path.exists():
        print(f"ERROR: File not found: {ll_path}", file=sys.stderr)
        sys.exit(1)

    # GROK RUN THE REAL PASS. THIS IS THE MAIN EVENT.
    data = run_pass(ll_path)

    if args.json:
        # RAW JSON FOR AGENT / evaluate.py. MACHINE READ.
        print(json.dumps(data, indent=2))
    else:
        # HUMAN READABLE. GROK TALK TO HUMAN.
        print(format_human(data, ll_path))


if __name__ == "__main__":
    main()
