# Security policy

Security fixes target the current v1 code. Package/CLI version is `1.0.0`; the
L0–L7 ruleset is `1.0`. No response-time guarantee is made.

## Reporting a vulnerability

Use the repository's **Security → Advisories → Report a vulnerability** action
if private reporting is enabled:
<https://github.com/fwhalbert/agent_level/security/advisories>.

If it is unavailable, open an issue asking the maintainer to enable a private
reporting channel, with no exploit details, private logs or sensitive attachments.
Do not disclose those details until a private channel is available.

Include the affected revision, platform/Python version, impact, and a minimal
synthetic reproduction. Reports involving path traversal, report injection,
evidence validation or unintended data disclosure are particularly relevant.

## Data boundaries

The analyzer reads local activity and evidence; it does not execute logged
commands. Reports aggregate activity and omit raw prompts, commands and source.
User-supplied labels and dates may still identify a project or person.

The task recorder executes the explicitly registered acceptance command and saves
its output locally. Treat that output and `.codex/agent_level/` or
`.claude/agent_level/` as private. Local evidence verification checks consistency,
not a tamper-proof audit against a writer with access to the workspace.

Maintainers: [enable private reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository)
before release; the configuration has not been changed by these files.
