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

from evaluate import ANALYZERS, RESULTS_DIR, run_analyzer


def collect_ll_files(target):
    target = Path(target).resolve()
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(target.rglob('*.ll'))
    return []


def md_cell(value, limit=140):
    s = '' if value is None else str(value)
    s = s.replace('|', '\\|').replace('\n', ' ')
    if len(s) > limit:
        s = s[:limit - 3] + '...'
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
    return (finding.get('heuristic'), finding.get('struct'))


def format_agreement(program_results, analyzer_names):
    # ONLY MEANINGFUL WITH 2+ ANALYZERS. SKIP OTHERWISE.
    if len(analyzer_names) < 2:
        return []
    lines = ['| Program | Agreed (all analyzers) | Tier-unique |',
             '|---------|------------------------|-------------|']
    for program in sorted(program_results):
        per_analyzer = program_results[program]
        keysets = {a: {agreement_key(f) for f in per_analyzer.get(a, {}).get('findings') or []}
                   for a in analyzer_names}
        agreed = set.intersection(*keysets.values()) if keysets else set()
        agreed_s = ', '.join(f'{h} {s}' for h, s in sorted(agreed, key=str)) or '(none)'
        unique_parts = []
        for a in analyzer_names:
            only = keysets[a] - agreed
            for h, s in sorted(only, key=str):
                unique_parts.append(f'{a}: {h} {s}')
        unique_s = '; '.join(unique_parts) or '(none)'
        lines.append(f'| {md_cell(program)} | {md_cell(agreed_s, 300)} | {md_cell(unique_s, 300)} |')
    return lines


def main():
    parser = argparse.ArgumentParser(description='Run false-sharing analyzers on unlabeled .ll files.')
    parser.add_argument('target', help='.ll file or directory of .ll files')
    parser.add_argument('--analyzers', default=','.join(ANALYZERS),
                        help='comma-separated analyzer names (default: all registered)')
    parser.add_argument('--out', default=str(RESULTS_DIR / 'scan_report.md'),
                        help='markdown report path (default: results/scan_report.md)')
    parser.add_argument('--json', action='store_true',
                        help='also dump raw combined findings to .json next to the .md')
    args = parser.parse_args()

    analyzer_names = [a.strip() for a in args.analyzers.split(',') if a.strip()]
    unknown = [a for a in analyzer_names if a not in ANALYZERS]
    if unknown:
        print(f'ERROR: unknown analyzer(s): {", ".join(unknown)}. '
              f'Registered: {", ".join(ANALYZERS)}')
        sys.exit(2)

    ll_files = collect_ll_files(args.target)
    if not ll_files:
        print(f'ERROR: no .ll files found at {args.target}')
        sys.exit(2)

    target_root = Path(args.target).resolve()
    error_count = 0
    program_results = {}

    for ll_file in ll_files:
        if target_root.is_dir():
            program = str(ll_file.relative_to(target_root).with_suffix('')).replace('\\', '/')
        else:
            program = ll_file.stem
        program_results[program] = {}
        for analyzer_name in analyzer_names:
            print(f'  scan: {program} [{analyzer_name}]', end=' ')
            findings, err = run_analyzer(ANALYZERS[analyzer_name], ll_file)
            if err:
                print(f'ERROR: {err}')
                error_count += 1
            else:
                print(f'{len(findings)} finding(s)')
            program_results[program][analyzer_name] = {'findings': findings, 'error': err}

    report_lines = [
        '# Scan Report — external programs (no ground truth)',
        '',
        f'Target: `{target_root}`',
        f'Analyzers: {", ".join(analyzer_names)}',
        f'Programs scanned: {len(program_results)}',
        '',
    ]

    for program in sorted(program_results):
        report_lines += [f'## {program}', '']
        rows = ['| Program | Analyzer | Heuristic | Severity | Struct/Object | Fields/Detail | Function/Line |',
                '|---------|----------|-----------|----------|---------------|---------------|---------------|']
        any_row = False
        for analyzer_name in analyzer_names:
            res = program_results[program][analyzer_name]
            if res['error']:
                rows.append(f'| {md_cell(program)} | {md_cell(analyzer_name)} | ERR | - | - '
                            f'| {md_cell(res["error"], 300)} | - |')
                any_row = True
                continue
            for finding in res['findings']:
                rows.append(finding_row(program, analyzer_name, finding))
                any_row = True
        if any_row:
            report_lines += rows
        else:
            report_lines.append('_No findings._')
        report_lines.append('')

    agreement = format_agreement(program_results, analyzer_names)
    if agreement:
        report_lines += ['## Cross-analyzer agreement', ''] + agreement + ['']

    if error_count:
        report_lines += [f'**Analyzer errors: {error_count}**', '']

    out_path = Path(args.out)
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
