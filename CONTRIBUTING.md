# Contributing to Agent Level

Contributions can improve bug fixes, log parsers, level definitions, evaluation
methodology, report UI, documentation, and integrations. Start with a small issue
that describes the behavior and evidence. No license grant has been added to this
checkout.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -v
```

Use Python 3.10+ and the standard library for runtime code. CI covers 3.10–3.13.
The installation test is skipped unless local build wheels are supplied. To run it:

```bash
python -m pip download --dest /tmp/agent-level-wheels 'setuptools>=64' wheel
AGENT_LEVEL_TEST_WHEELHOUSE=/tmp/agent-level-wheels python -m unittest discover -v
```

The smoke test installs into a temporary venv, checks bootstrap and legacy aliases,
then installs a regular wheel and checks commands away from the source checkout.
The wheel download needs network access; the installation test itself is offline.

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
