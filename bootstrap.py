"""Reference this checkout from Codex global instructions."""

import argparse
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tempfile

from auto_eval_session_notice import INSTRUCTION_END, INSTRUCTION_START

IMPORT_START = "<!-- agent-level:task-evidence-import:start -->"
IMPORT_END = "<!-- agent-level:task-evidence-import:end -->"
IMPORT_HEADER = ("## agent_level: automatic task evidence\n\n"
                 "Read and follow the task evidence workflow in:\n")
COMMANDS_HEADER = ("\n## agent_level: installed commands\n\n"
                   "Use these commands without activating a virtual environment:\n")


def write_text(path, content):
    if path.is_symlink():
        raise ValueError(f"refusing to replace symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if path.exists():
            os.fchmod(fd, stat.S_IMODE(path.stat().st_mode))
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def enable_instructions(codex_home, source):
    instructions = source / "AGENTS.md"
    source_text = instructions.read_text(encoding="utf-8")
    start = source_text.find(INSTRUCTION_START)
    end = source_text.find(INSTRUCTION_END, start)
    if start < 0 or end < 0:
        raise ValueError("task evidence section is missing from source AGENTS.md")
    section = f"{IMPORT_HEADER}@{instructions}\n"
    agents = codex_home / "AGENTS.md"
    if agents.is_symlink():
        raise ValueError(f"refusing to replace symlink: {agents}")
    current = agents.read_text(encoding="utf-8") if agents.exists() else ""
    reference = re.search(
        rf"(?m)^{re.escape(IMPORT_HEADER)}@[^\n]+\n?"
        rf"(?:{re.escape(COMMANDS_HEADER)}- Recorder: [^\n]+\n- Report: [^\n]+\n)?", current)
    opening, closing = INSTRUCTION_START, INSTRUCTION_END
    if IMPORT_START in current or IMPORT_END in current:
        opening, closing = IMPORT_START, IMPORT_END
    # Enabling this checkout must preserve the canonical instructions themselves.
    if agents == instructions:
        updated = current
    elif opening in current or closing in current:
        old_start = current.find(opening)
        old_end = current.find(closing, old_start)
        if old_start < 0 or old_end < 0:
            raise ValueError(f"incomplete task evidence section: {agents}")
        suffix = current[old_end + len(closing):].removeprefix("\n")
        updated = current[:old_start] + section + suffix
    elif reference:
        updated = current[:reference.start()] + section + current[reference.end():]
    else:
        legacy = (r"(?m)^## Automatic Task Evidence\n\n"
                  r"For substantive engineering tasks, follow "
                  r"\[task evidence instructions\]\([^\n)]*AUTO_EVALUATION\.md\)\.\n?")
        clean = re.sub(legacy, "", current).strip()
        updated = clean + "\n\n" + section if clean else section
    if updated != current:
        write_text(agents, updated)


def setup_main(argv=None):
    return main(argv, public=True)


def main(argv=None, *, public=False):
    parser = argparse.ArgumentParser(
        prog="agent-level setup" if public else None,
        description="Enable task recording globally by referencing this source checkout.")
    parser.add_argument("--codex-home", type=Path,
                        help="default: CODEX_HOME, else ~/.codex")
    args = parser.parse_args(argv)
    try:
        source = Path(__file__).resolve().parent
        if not (source / "agent-level").is_file() or not (source / "AGENTS.md").is_file():
            raise ValueError("run setup from the Agent Level source checkout")
        codex_home = (args.codex_home or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
        codex_home = codex_home.expanduser().resolve()
        enable_instructions(codex_home, source)
    except (OSError, ValueError) as exc:
        print(f"[error] setup failed: {exc}", file=sys.stderr)
        return 2
    print(f"[ok] global instructions: {codex_home / 'AGENTS.md'}")
    print("[next] Start a new Codex session. Keep this checkout available.")
    print("[next] Run directly from any project directory:")
    print("  " + shlex.join([sys.executable, str(source / "agent-level")]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
