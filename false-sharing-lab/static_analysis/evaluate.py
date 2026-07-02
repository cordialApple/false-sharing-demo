#!/usr/bin/env python3
# EVALUATE.PY - GROK SCORE HEURISTICS. GROUND TRUTH CORPUS. HONEST NUMBERS.
# GROK NOT LIE. IF TIER-1 MISS, TABLE SHOW MISS. IF TIER-1 FP, TABLE SHOW FP.
# WHOLE POINT: MEASURE COVERAGE GAPS. NOT HIDE THEM.
#
# USAGE: python evaluate.py
# OUTPUT: markdown score table to STDOUT + results/heuristic_scores_<analyzer>.md
# EXIT 0 = NO UNEXPECTED FP, FN, OR ANALYZER ERROR. EXIT 1 OTHERWISE.
#          GAPS (known_limitation=true) AND KNOWN-FP (known_fp=[...]) ARE ALLOWED.

import json
import subprocess
import sys
import os
from pathlib import Path

# ============================================================
# ANALYZER REGISTRY. NAME -> COMMAND TEMPLATE.
# TEMPLATE USES {ll} AS PLACEHOLDER FOR .ll FILE PATH.
# TIER-1: PYTHON IR ANALYZER. SHIPS WITH THIS LAB.
# TIER-2: (COMMENTED) OPT LLVM PASS. UNCOMMENT WHEN PASS LANDS.
# ============================================================
ANALYZERS = {
    # {python} = sys.executable. WINDOWS python3 IS FAKE STORE STUB. GROK NOT TRUST NAME.
    'tier1': ['{python}', '{ir_analyzer}', '{ll}', '--json'],
    # TIER-2: REAL LLVM PASS. WRAPPER RUN OPT WITH FalseSharingPass.so.
    'tier2': ['{python}', '{tier2_analyzer}', '{ll}', '--json'],
}

# ============================================================
# PATH CONSTANTS. ALL ABSOLUTE. GROK HATE RELATIVE PATH.
# ============================================================
THIS_DIR     = Path(__file__).parent.resolve()
CORPUS_DIR   = THIS_DIR / 'corpus'
IR_CACHE_DIR = CORPUS_DIR / 'ir'
LABELS_FILE  = CORPUS_DIR / 'labels.json'
IR_ANALYZER  = THIS_DIR / 'ir_analyzer.py'
RESULTS_DIR  = THIS_DIR / 'results'

# CACHE LINE SIZE. UNIVERSE CONSTANT.
CACHE_LINE = 64


def win_to_wsl(path):
    # GROK CONVERT WINDOWS PATH TO WSL /mnt/ PATH.
    # C:\foo\bar -> /mnt/c/foo/bar. ONLY CALLED ON WINDOWS HOST.
    p = str(path).replace('\\', '/')
    if len(p) >= 2 and p[1] == ':':
        drive = p[0].lower()
        p = '/mnt/' + drive + p[2:]
    return p


def compile_to_ir(c_file, ll_file):
    # GROK COMPILE .c TO .ll VIA CLANG.
    # DUAL MODE: WINDOWS HOST = WSL PREFIX. LINUX CI = CLANG DIRECT.
    # -O0 = ALL STORES SURVIVE. -g = SOURCE LINES IN DEBUG METADATA.
    # -std=c11 = _Atomic SUPPORT.
    # SKIP IF CACHED (ll_file EXISTS AND NEWER THAN c_file).
    if ll_file.exists() and ll_file.stat().st_mtime >= c_file.stat().st_mtime:
        return True, 'cached'

    # ENSURE OUTPUT SUBDIR EXISTS. CORPUS MAY USE basic/ advanced/ LAYOUT.
    ll_file.parent.mkdir(parents=True, exist_ok=True)

    if os.name == 'nt':
        # WINDOWS HOST. CLANG LIVE IN WSL. TRANSLATE PATH. RUN VIA WSL.
        wsl_c  = win_to_wsl(c_file)
        wsl_ll = win_to_wsl(ll_file)
        cmd = ['wsl', '-e', 'sh', '-c',
               f"clang -S -emit-llvm -O0 -g -std=c11 -pthread '{wsl_c}' -o '{wsl_ll}' 2>&1"]
        result = subprocess.run(cmd, capture_output=True, text=True)
    else:
        # LINUX CI. CLANG NATIVE. RUN DIRECT. NO WSL NONSENSE.
        cmd = ['clang', '-S', '-emit-llvm', '-O0', '-g', '-std=c11', '-pthread',
               str(c_file), '-o', str(ll_file)]
        result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        msg = (result.stdout or '') + (result.stderr or '')
        return False, msg.strip()
    return True, 'compiled'


def run_analyzer(analyzer_cmd_template, ll_file):
    # GROK RUN ANALYZER. PARSE JSON. RETURN (findings_list, error_str_or_None).
    # TEMPLATE SUBSTITUTION: {ir_analyzer} = tier1 script, {tier2_analyzer} = tier2 wrapper.
    cmd = []
    for tok in analyzer_cmd_template:
        tok = tok.replace('{python}', sys.executable)
        tok = tok.replace('{ll}', str(ll_file))
        tok = tok.replace('{ir_analyzer}', str(IR_ANALYZER))
        tok = tok.replace('{tier2_analyzer}', str(THIS_DIR / 'tier2_analyzer.py'))
        cmd.append(tok)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None, f"analyzer exit {result.returncode}: {result.stderr.strip()}"
    try:
        data = json.loads(result.stdout)
        return data.get('findings', []), None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


def finding_matches(finding, expected_entry):
    # GROK CHECK: DOES ACTUAL FINDING MATCH EXPECTED ENTRY?
    # HEURISTIC MUST MATCH EXACTLY.
    # struct_contains (IF NOT EMPTY/NULL) MUST BE SUBSTRING OF finding['struct'].
    if finding['heuristic'] != expected_entry['heuristic']:
        return False
    sc = expected_entry.get('struct_contains')
    if sc:  # EMPTY STRING OR NULL = NO STRUCT CONSTRAINT.
        struct_name = finding.get('struct', '')
        if sc not in struct_name:
            return False
    return True


def evaluate_case(case_label, actual_findings):
    # GROK EVALUATE ONE CASE. RETURN LIST OF VERDICTS.
    # EACH VERDICT IS A DICT WITH keys: type, heuristic, struct_contains, finding.
    # type: PASS | MISS | GAP | FP | KNOWN-FP
    expected    = case_label['expected']         # LIST OF EXPECTED ENTRIES.
    known_limit = case_label.get('known_limitation', False)
    # KNOWN-FP: LIST OF HEURISTIC NAMES THAT ARE KNOWN FALSE POSITIVES.
    # FINDING WHOSE HEURISTIC IN THIS LIST -> KNOWN-FP. NOT PENALISED. NOT EXIT 1.
    known_fp_list = case_label.get('known_fp', [])
    verdicts    = []

    # TRACK WHICH FINDINGS GOT MATCHED. UNMATCHED = FP OR KNOWN-FP.
    matched_finding_indices = set()

    # CHECK EACH EXPECTED ENTRY AGAINST ACTUAL FINDINGS.
    for exp in expected:
        matched = False
        for i, finding in enumerate(actual_findings):
            if finding_matches(finding, exp):
                matched = True
                matched_finding_indices.add(i)
                verdicts.append({
                    'type': 'PASS',
                    'heuristic': exp['heuristic'],
                    'struct_contains': exp.get('struct_contains'),
                    'finding': finding,
                })
                break  # ONE MATCH IS ENOUGH FOR THIS EXPECTED ENTRY.

        if not matched:
            # EXPECTED FINDING NOT PRODUCED. GAP OR MISS?
            if known_limit:
                # KNOWN LIMITATION. NOT A TIER-1 BUG. COUNT AS GAP.
                verdict_type = 'GAP'
            else:
                # UNEXPECTED MISS. TIER-1 SHOULD HAVE CAUGHT THIS. FN.
                verdict_type = 'MISS'
            verdicts.append({
                'type': verdict_type,
                'heuristic': exp['heuristic'],
                'struct_contains': exp.get('struct_contains'),
                'finding': None,
            })

    # ANY ACTUAL FINDING NOT MATCHED BY AN EXPECTED ENTRY = FP OR KNOWN-FP.
    # KNOWN-FP: HEURISTIC IN known_fp_list -> SHOWN AS KNOWN-FP, NOT PENALISED.
    for i, finding in enumerate(actual_findings):
        if i not in matched_finding_indices:
            if finding['heuristic'] in known_fp_list:
                verdict_type = 'KNOWN-FP'
            else:
                verdict_type = 'FP'
            verdicts.append({
                'type': verdict_type,
                'heuristic': finding['heuristic'],
                'struct_contains': None,
                'finding': finding,
            })

    # IF EXPECTED IS EMPTY AND NO FINDINGS: IMPLICIT PASS (TN).
    if not expected and not actual_findings:
        verdicts.append({
            'type': 'PASS',
            'heuristic': '(none)',
            'struct_contains': None,
            'finding': None,
        })

    return verdicts


def compute_metrics(all_case_results):
    # GROK COMPUTE PER-HEURISTIC TP/FP/FN/GAP/KNOWN_FP AND OVERALL METRICS.
    # GAP VERDICTS NOT COUNTED AS FN (ALLOWED GAPS).
    # KNOWN-FP VERDICTS NOT COUNTED AS FP (KNOWN FALSE POSITIVES, ALLOWED).
    from collections import defaultdict
    heuristics = defaultdict(lambda: {'TP': 0, 'FP': 0, 'FN': 0, 'GAP': 0, 'KNOWN_FP': 0})

    for case_name, verdicts in all_case_results.items():
        for v in verdicts:
            h = v['heuristic']
            t = v['type']
            if t == 'PASS' and h != '(none)':
                heuristics[h]['TP'] += 1
            elif t == 'FP':
                heuristics[h]['FP'] += 1
            elif t == 'MISS':
                heuristics[h]['FN'] += 1
            elif t == 'GAP':
                heuristics[h]['GAP'] += 1
            elif t == 'KNOWN-FP':
                # KNOWN-FP: TALLY SEPARATELY. NOT FP. NOT EXIT 1.
                heuristics[h]['KNOWN_FP'] += 1

    return dict(heuristics)


def precision_recall(tp, fp, fn):
    # GROK COMPUTE PRECISION AND RECALL. HANDLE ZERO DIVISION.
    prec = tp / (tp + fp) if (tp + fp) > 0 else float('nan')
    rec  = tp / (tp + fn) if (tp + fn) > 0 else float('nan')
    return prec, rec


def format_score_table(metrics):
    # GROK FORMAT MARKDOWN TABLE. HEURISTIC | TP | FP | FN | GAP | KNOWN-FP | PREC | RECALL
    lines = []
    lines.append('| Heuristic | TP | FP | FN | GAP | KNOWN-FP | Precision | Recall |')
    lines.append('|-----------|----|----|----|----|----------|-----------|--------|')

    total = {'TP': 0, 'FP': 0, 'FN': 0, 'GAP': 0, 'KNOWN_FP': 0}
    for h in sorted(metrics.keys()):
        m = metrics[h]
        tp, fp, fn, gap, kfp = m['TP'], m['FP'], m['FN'], m['GAP'], m['KNOWN_FP']
        prec, rec = precision_recall(tp, fp, fn)
        prec_s = f'{prec:.2f}' if prec == prec else 'N/A'  # NaN CHECK.
        rec_s  = f'{rec:.2f}'  if rec == rec  else 'N/A'
        lines.append(f'| {h} | {tp} | {fp} | {fn} | {gap} | {kfp} | {prec_s} | {rec_s} |')
        total['TP']      += tp
        total['FP']      += fp
        total['FN']      += fn
        total['GAP']     += gap
        total['KNOWN_FP'] += kfp

    # OVERALL ROW.
    tp, fp, fn = total['TP'], total['FP'], total['FN']
    prec, rec = precision_recall(tp, fp, fn)
    prec_s = f'{prec:.2f}' if prec == prec else 'N/A'
    rec_s  = f'{rec:.2f}'  if rec == rec  else 'N/A'
    lines.append(
        f'| **TOTAL** | **{tp}** | **{fp}** | **{fn}** | **{total["GAP"]}** '
        f'| **{total["KNOWN_FP"]}** | **{prec_s}** | **{rec_s}** |'
    )

    return '\n'.join(lines)


def format_case_detail(all_case_results):
    # GROK FORMAT PER-CASE DETAIL TABLE FOR RESULTS FILE.
    # COLUMNS: CASE | EXPECTED | GOT | VERDICT
    # FOR FP/KNOWN-FP: EXPECTED=(none), GOT=ACTUAL FINDING. NOTHING WAS EXPECTED.
    # FOR MISS/GAP: EXPECTED=EXPECTED ENTRY, GOT=(none). FINDING ABSENT.
    # FOR PASS: EXPECTED=EXPECTED ENTRY, GOT=ACTUAL FINDING.
    lines = []
    lines.append('| Case | Expected | Got | Verdict |')
    lines.append('|------|----------|-----|---------|')

    for case_name, verdicts in sorted(all_case_results.items()):
        for v in verdicts:
            t = v['type']
            f = v['finding']
            got_s = f'{f["heuristic"]} {f.get("struct","")}'.strip() if f else '(none)'

            if t in ('FP', 'KNOWN-FP'):
                # UNEXPECTED (OR KNOWN) FINDING. NOTHING WAS EXPECTED. SHOW EMPTY EXPECTED.
                exp_s = '(none expected)'
            else:
                # PASS / MISS / GAP. SHOW WHAT WAS EXPECTED.
                h  = v['heuristic']
                sc = v['struct_contains'] or ''
                exp_s = f'{h} ({sc})' if sc else h

            lines.append(f'| {case_name} | {exp_s} | {got_s} | {t} |')

    return '\n'.join(lines)


def get_ll_path(case):
    # GROK DERIVE IR CACHE PATH FOR A CASE.
    # SUPPORTS BOTH FLAT (tp_h2.c) AND SUBDIR (basic/tp_h2.c) CORPUS LAYOUTS.
    # IR CACHE MIRRORS SUBDIR: corpus/ir/basic/tp_h2.ll
    rel = Path(case['file'])          # e.g. "basic/tp_h2_tid_array.c" or "tp_h2.c"
    subdir = rel.parent               # "basic" or "."
    stem   = rel.stem                 # "tp_h2_tid_array"
    return IR_CACHE_DIR / subdir / (stem + '.ll')


def main():
    # GROK MAIN EVALUATION LOOP.
    # 1. LOAD LABELS.
    # 2. COMPILE EACH .c TO .ll (CACHED). SUBDIR LAYOUT SUPPORTED.
    # 3. RUN EACH REGISTERED ANALYZER ON EACH .ll.
    # 4. MATCH FINDINGS TO LABELS. KNOWN-FP SHOWN SEPARATELY. NOT PENALISED.
    # 5. COMPUTE METRICS.
    # 6. PRINT TABLE. WRITE RESULTS FILE.
    # 7. EXIT 0 IF NO UNEXPECTED FP/FN. EXIT 1 OTHERWISE.

    # STEP 1: LOAD LABELS.
    with open(LABELS_FILE, 'r') as f:
        label_data = json.load(f)
    cases = label_data['cases']
    print(f'Loaded {len(cases)} labeled cases from {LABELS_FILE}')

    # ENSURE DIRS EXIST.
    IR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # STEP 2: COMPILE EACH .c TO .ll.
    print('\n--- COMPILE CORPUS ---')
    compile_errors = []
    for case in cases:
        # CASE FILE PATH RELATIVE TO CORPUS DIR. MAY INCLUDE SUBDIR.
        c_file  = CORPUS_DIR / case['file']
        ll_file = get_ll_path(case)
        ok, msg = compile_to_ir(c_file, ll_file)
        status = 'OK' if ok else 'ERROR'
        print(f'  {status}: {case["file"]} ({msg})')
        if not ok:
            compile_errors.append(case['file'])

    if compile_errors:
        print(f'\nERROR: {len(compile_errors)} compile failures. Cannot evaluate.')
        sys.exit(2)

    # STEP 3 + 4: FOR EACH ANALYZER, RUN AND MATCH.
    exit_code = 0
    for analyzer_name, cmd_template in ANALYZERS.items():
        print(f'\n--- ANALYZER: {analyzer_name} ---')
        all_case_results = {}  # CASE_NAME -> [VERDICTS]

        for case in cases:
            rel      = Path(case['file'])
            ll_file  = get_ll_path(case)
            # FULL RELATIVE PATH MINUS .c AS CASE NAME. STEM ALONE COLLIDE IF
            # basic/ AND advanced/ EVER SHARE A FILENAME. REVIEW CAUGHT THIS.
            case_name = str(rel.with_suffix('')).replace('\\', '/')

            # RUN ANALYZER.
            findings, err = run_analyzer(cmd_template, ll_file)
            if err:
                print(f'  ANALYZER ERROR on {case_name}: {err}')
                all_case_results[case_name] = [{'type': 'ERROR', 'heuristic': 'N/A',
                                                 'struct_contains': None, 'finding': None}]
                continue

            # MATCH FINDINGS TO LABELS.
            verdicts = evaluate_case(case, findings)
            all_case_results[case_name] = verdicts

        # STEP 5: COMPUTE METRICS.
        metrics = compute_metrics(all_case_results)

        # STEP 6: FORMAT OUTPUT.
        score_table = format_score_table(metrics)
        case_detail  = format_case_detail(all_case_results)

        # COUNT FP/FN/GAP/KNOWN-FP (KNOWN-FP NOT IN FP. NOT EXIT 1).
        total_fp   = sum(m['FP']       for m in metrics.values())
        total_fn   = sum(m['FN']       for m in metrics.values())
        total_gap  = sum(m['GAP']      for m in metrics.values())
        total_kfp  = sum(m['KNOWN_FP'] for m in metrics.values())
        # COUNT ERROR VERDICTS TOO. REVIEW FOUND: ANALYZER CRASH ON EVERY CASE
        # SCORED AS GREEN BECAUSE ERROR FELL THROUGH ALL METRIC BUCKETS. NEVER AGAIN.
        total_err  = sum(1 for vs in all_case_results.values()
                         for v in vs if v['type'] == 'ERROR')

        # MARKDOWN REPORT CONTENT.
        report_lines = [
            f'# Heuristic Score Report — Analyzer: {analyzer_name}',
            '',
            '## Score Table',
            '',
            score_table,
            '',
            '## Per-Case Detail',
            '',
            case_detail,
            '',
            '## Summary',
            '',
            f'- **Unexpected FP** (false alarms on TN cases): {total_fp}',
            f'- **Unexpected FN / MISS** (TP cases not caught): {total_fn}',
            f'- **Known Gaps** (known_limitation=true, not penalized): {total_gap}',
            f'- **Known FP** (known_fp=[...], not penalized): {total_kfp}',
            f'- **Analyzer errors** (case not analyzed at all): {total_err}',
            '',
        ]
        # NO HARD-CODED WEAKNESS PROSE HERE. PER-CASE DETAIL TELL THE STORY.
        # PROSE GO STALE WHEN HEURISTIC GET FIXED. TABLE NEVER LIE.

        report_md = '\n'.join(report_lines)

        # PRINT SCORE TABLE TO STDOUT.
        print()
        print(score_table)
        print()
        print(f'FP={total_fp} FN={total_fn} GAP={total_gap} KNOWN-FP={total_kfp} ERR={total_err}')

        # WRITE RESULTS FILE. ONE FILE PER ANALYZER. NO OVERWRITE WAR.
        results_file = RESULTS_DIR / f'heuristic_scores_{analyzer_name}.md'
        with open(results_file, 'w') as f:
            f.write(report_md)
        print(f'\nResults written to: {results_file}')

        # EXIT CODE: 1 IF UNEXPECTED FP, FN, OR ANALYZER ERROR. GAPS/KNOWN-FP FORGIVEN.
        if total_fp > 0 or total_fn > 0 or total_err > 0:
            exit_code = 1

    # GROK DONE. HONEST RESULT. NO FUDGE.
    if exit_code == 0:
        print('\nAll clear: no unexpected FP or FN. Gaps (known_limitation) and KNOWN-FP are allowed.')
    else:
        print('\nFinished with unexpected FP/FN. See score table above for details.')
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
