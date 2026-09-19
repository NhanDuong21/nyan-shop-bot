// NYAN-ANTIGRAVITY-SINGLE-WRITER-V1: fail-closed PreToolUse handler.

for await (const _chunk of process.stdin) {
  // Drain the complete hook request before returning the decision.
}

process.stdout.write(
  `${JSON.stringify({
    decision: "deny",
    reason:
      "Nyan UI tasks permit exactly one Antigravity writer; shell, background, " +
      "permission-escalation, scheduling, and delegation tools are disabled before execution.",
  })}\n`,
);
