# Contributing to Agent Level

Contributions can improve bug fixes, log parsers, level definitions, evaluation
methodology, report UI, documentation, and integrations. Start with a small issue
that describes the behavior and evidence. This project is licensed under the
[MIT License](LICENSE).

## Development

Run the source tests from the repository root with Python 3.9+ and Git:

```bash
python3 -m unittest discover -v
```

Runtime code and tests use the Python standard library. Source tests run directly
from the checkout without installing the package or downloading build dependencies.
CI covers Python 3.9–3.13 on Linux and macOS. It runs the source suite and checks
global setup and direct source commands with temporary configuration and project
paths containing spaces. It does not verify package installation or built wheels.

## Evidence and review

- Keep package/CLI version `1.0.0` and ruleset `1.0` unless an upgrade is explicitly requested.
- Preserve thresholds and distinguish observed behavior from verified outcomes.
  Discuss definition changes with counterexamples and measurable evidence; avoid
  raising levels solely to make reports look better.
- Include synthetic fixtures for parsers and regression tests for behavior changes.
  Never commit personal logs, prompts, source snippets, tokens or acceptance output.
- Keep reports offline and escape dynamic content. Check English and Chinese UI.
- Use [the recording workflow](AGENTS.md) when working as an agent; evidence stays local.
- Explain the problem, the resulting behavior, compatibility effects and tests in
  the PR. Keep commits focused. Do not add dependencies without a concrete need.

Generate a synthetic report with `python examples/generate_report.py`; see
[examples](examples/README.md) for output paths. Use the security process in
[SECURITY.md](SECURITY.md) for sensitive findings.
