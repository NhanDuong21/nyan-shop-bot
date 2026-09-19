---
trigger: always_on
glob:
description: Nyan Shop Bot UI worker boundary
---

# Nyan UI worker boundary

This Antigravity workspace rule is intentionally duplicated from the mandatory repository policy in `AGENTS.md`. Antigravity-only rule marker: `NYAN-ANTIGRAVITY-RULE-V1`.

- Edit only the exact `admin/src/features/<task>/**` paths named by the trusted task.
- Keep the Codex-owned app, domain, ports, data, generated types/fixtures, routing, shared components, manifests, lockfiles, build/test configuration, Docker/nginx, CI, runner, rules, and gates unchanged.
- Use existing interfaces and injected data only. Never call `fetch` directly, hardcode API results, invent balance or supplier state, add a dependency, disable a test, or enable a real purchase/payment/refund action.
- Implement the requested visual hierarchy, layout, responsive behavior, animation, and component-local interaction while preserving loading, error, empty, and success states.
- If the task needs an out-of-scope architecture, API, auth, business, dependency, or configuration change, return `BLOCKED` to the coordinator. Do not make the change and do not ask the owner to relay it.
- Do not create, delegate to, or resume a subagent, background agent, or second writer. This conversation is the only UI writer.
- The committed workspace `PreToolUse` hook hard-denies shell, background-task, scheduling, permission-escalation, and collaboration tools before execution. Do not try to bypass, disable, rename, or edit that hook or launch a nested `agy` process by any route.
- Report every shell-based check as `NOT_RUN`; the coordinator and CI run the existing checks after validating the bounded diff. Never claim a denied or unavailable check passed.
