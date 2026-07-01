"""Entry point for AI Personal OS.

Phase 1 skeleton (Build Plan T0.1). This prints a liveness banner so the
repository, virtual environment, and toolchain can be verified end to end
before any real subsystems exist. Real behaviour (ingestion, retrieval,
reasoning) is introduced in later milestones per the Build Plan.
"""

import sys


def main() -> None:
    """Print the application liveness banner."""
    # Force UTF-8 output: on Windows, stdout defaults to a legacy code page
    # (e.g. cp1252) which mangles the em dash in a UTF-8 terminal.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("AI Personal OS — alive")


if __name__ == "__main__":
    main()
