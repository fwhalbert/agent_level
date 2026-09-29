#!/usr/bin/env python3
"""Render a deterministic example using only the checked-in synthetic logs."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import assess
from assessment.logs import scan_codex
from assessment.web import render_html


def sample_bundle():
    metrics = scan_codex(ROOT / 'examples/sample-data/codex', None, None,
                         project_dir=Path('/synthetic/agent-level-demo'))
    result = assess.evaluate(metrics)
    report = assess.build_report(metrics, result, None, None,
                                 report_name='Agent Level · Synthetic example')
    report['generated_at'] = '2026-09-12T00:00:00+00:00'
    report['anthropic_evaluation']['synthetic'] = True
    return {
        'version': assess.VERSION, 'ruleset_version': assess.RULESET_VERSION,
        'report_name': report['report_name'], 'report_file_stem': 'agent-level',
        'synthetic': True, 'reports': {'codex': report},
        'merge_note': 'Synthetic example only. No real task outcomes or capability claims.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'out/agent_level/example')
    args = parser.parse_args(argv)
    bundle = sample_bundle()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for extension, content in (
        ('html', render_html(bundle)),
        ('json', json.dumps(bundle, ensure_ascii=False, indent=2)),
        ('md', assess.render_report(bundle['reports']['codex'], markdown=True)),
    ):
        (args.output_dir / f'agent-level.{extension}').write_text(content + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
