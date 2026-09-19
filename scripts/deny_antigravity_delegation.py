"""NYAN-ANTIGRAVITY-SINGLE-WRITER-V1 pre-tool hard denial."""

from __future__ import annotations

import json
import sys


def main() -> int:
    """Deny every collaboration tool matched by the trusted workspace hook."""

    # Drain stdin so the hook protocol can close cleanly. The matcher in the
    # committed hooks file selects only collaboration tools; fail closed if the
    # payload is malformed or the hook is accidentally applied more broadly.
    sys.stdin.read()
    json.dump(
        {
            "decision": "deny",
            "reason": (
                "Nyan UI tasks permit exactly one Antigravity writer; "
                "delegation and subagent tools are disabled before execution."
            ),
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
