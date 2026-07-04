#!/usr/bin/env python3
# SCAN.PY - FINDINGS REPORT FOR EXTERNAL PROGRAMS. NO LABELS. NO GROUND TRUTH.
# EVALUATE.PY SCORE CORPUS. SCAN.PY JUST REPORT WHAT ANALYZERS SEE.
#
# USAGE: python scan.py <file.ll | dir-of-.ll> [--analyzers tier1,tier2]
#                       [--out results/scan_<name>.md] [--json]
# EXIT 0 = ALL ANALYZERS RAN CLEAN. FINDINGS NOT FAILURES. EXIT 1 = ANALYZER ERROR.

import argparse
import json
import sys
from pathlib import Path

from evaluate import ANALYZERS, RESULTS_DIR, rel_name, run_analyzer


def collect_ll_files(target):
    target = Path(target).resolve()
    if target.is_file():
        files = [target] if target.suffix == '.ll' else []
    elif target.is_dir():
        files = sorted(target.rglob('*.ll'))
    else:
        files = []
    return files, target


def md_cell(value, limit=140):
    s = '' if value is None else str(value)
    s = s.replace('\n', ' ')
    truncated = len(s) > limit
    if truncated:
        s = s[:limit - 3].rstrip('\\')
    s = s.replace('|', '\\|')
    if truncated:
        s += '...'
    return s or '-'


def finding_row(program, analyzer, finding):
    return (
        f'| {md_cell(program)} '
        f'| {md_cell(analyzer)} '
        f'| {md_cell(finding.get("heuristic"))} '
        f'| {md_cell(finding.get("severity"))} '
        f'| {md_cell(finding.get("struct"))} '
        f'| {md_cell(finding.get("detail") or finding.get("fields"))} '
        f'| {md_cell(finding.get("thread_fn") or finding.get("function") or finding.get("line"))} |'
    )


def agreement_key(finding):
    return (finding.get('heuristic'), finding.get('struct'), finding.get('thread_fn'))


def fmt_key(key):
    return ' '.join(str(p) for p in key if p)


def format_agreement(program_results, analyzer_names):
    # ONLY MEANINGFUL WITH 2+ ANALYZERS.
    if len(analyzer_names) < 2:
        return []
    lines = ['| Program | Agreed (all analyzers) | Tier-unique |',
             '|---------|------------------------|-------------|']
    for program in sorted(program_results):
        per_analyzer = program_results[program]
        if any(per_analyzer[a].get('error') for a in analyzer_names):
            lines.append(f'| {md_cell(program)} | (not computed: analyzer error) '
                         '| (not computed: analyzer error) |')
            continue
        keysets = {a: {agreement_key(f) for f in per_analyzer[a].get('findings') or []}
                   for a in analyzer_names}
        agreed = set.intersection(*keysets.values())
        agreed_s = ', '.join(fmt_key(k) for k in sorted(agreed, key=str)) or '(none)'
        unique_parts = []
        for a in analyzer_names:
            by_heuristic = {}
            for key in sorted(keysets[a] - agreed, key=str):
                by_heuristic.setdefault(key[0], []).append(key)
            for h, keys in sorted(by_heuristic.items(), key=str):
                if len(keys) > 3:
                    unique_parts.append(f'{a}: {h} ×{len(keys)}')
                else:
                    unique_parts.extend(f'{a}: {fmt_key(k)}' for k in keys)
        unique_s = '; '.join(unique_parts) or '(none)'
        lines.append(f'| {md_cell(program)} | {md_cell(agreed_s, 300)} | {md_cell(unique_s, 300)} |')
    return lines


def main():
    parser = argparse.ArgumentParser(description='Run false-sharing analyzers on unlabeled .ll files.')
    parser.add_argument('target', help='.ll file or directory of .ll files')
    parser.add_argument('--analyzers', default=','.join(ANALYZERS),
                        help='comma-separated analyzer names (default: all registered)')
    parser.add_argument('--out', default=None,
                        help='markdown report path (default: results/scan_<target-name>.md)')
    parser.add_argument('--json', action='store_true',
                        help='also dump raw combined findings to .json next to the .md')
    args = parser.parse_args()

    analyzer_names = list(dict.fromkeys(
        a.strip() for a in args.analyzers.split(',') if a.strip()))
    unknown = [a for a in analyzer_names if a not in ANALYZERS]
    if unknown:
        print(f'ERROR: unknown analyzer(s): {", ".join(unknown)}. '
              f'Registered: {", ".join(ANALYZERS)}')
        sys.exit(2)

    ll_files, target_root = collect_ll_files(args.target)
    if not ll_files:
        print(f'ERROR: no .ll files found at {args.target}')
        sys.exit(2)

    is_dir = target_root.is_dir()
    program_results = {}

    for ll_file in ll_files:
        if is_dir:
            program = rel_name(ll_file.relative_to(target_root))
        else:
            program = ll_file.stem
        program_results[program] = {}
        for analyzer_name in analyzer_names:
            print(f'  scan: {program} [{analyzer_name}]', end=' ')
            findings, err = run_analyzer(ANALYZERS[analyzer_name], ll_file)
            if err:
                print(f'ERROR: {err}')
            else:
                print(f'{len(findings)} finding(s)')
            program_results[program][analyzer_name] = {'findings': findings, 'error': err}

    error_count = sum(1 for per_analyzer in program_results.values()
                      for res in per_analyzer.values() if res['error'])

    try:
        display_target = target_root.relative_to(Path.cwd()).as_posix()
    except ValueError:
        display_target = Path(args.target).as_posix()

    report_lines = [
        '# Scan Report — external programs (no ground truth)',
        '',
        f'Target: `{display_target}`',
        f'Analyzers: {", ".join(analyzer_names)}',
        f'Programs scanned: {len(program_results)}',
        '',
    ]

    for program in sorted(program_results):
        report_lines += [f'## {program}', '']
        rows = ['| Program | Analyzer | Heuristic | Severity | Struct/Object | Fields/Detail | Function/Line |',
                '|---------|----------|-----------|----------|---------------|---------------|---------------|']
        for analyzer_name in analyzer_names:
            res = program_results[program][analyzer_name]
            if res['error']:
                rows.append(finding_row(program, analyzer_name,
                                        {'heuristic': 'ERR', 'detail': res['error']}))
                continue
            for finding in res['findings']:
                rows.append(finding_row(program, analyzer_name, finding))
        if len(rows) > 2:
            report_lines += rows
        else:
            report_lines.append('_No findings._')
        report_lines.append('')

    agreement = format_agreement(program_results, analyzer_names)
    if agreement:
        report_lines += ['## Cross-analyzer agreement', ''] + agreement + ['']

    if error_count:
        report_lines += [f'**Analyzer errors: {error_count}**', '']

    if args.out:
        out_path = Path(args.out)
    else:
        name = target_root.name if is_dir else target_root.stem
        out_path = RESULTS_DIR / f'scan_{name}.md'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(report_lines), encoding='utf-8')
    print(f'\nReport written to: {out_path}')

    if args.json:
        json_path = out_path.with_suffix('.json')
        json_path.write_text(json.dumps(program_results, indent=2), encoding='utf-8')
        print(f'Raw findings written to: {json_path}')

    sys.exit(1 if error_count else 0)


if __name__ == '__main__':
    main()
