---
trigger: always_on
glob:
description: Nyan Shop Bot UI worker boundary
---

# Nyan UI worker boundary

This Antigravity workspace rule is intentionally duplicated from the mandatory repository policy in `AGENTS.md`. Antigravity-only rule marker: `NYAN-ANTIGRAVITY-RULE-V1`.

- Read the project-local `/impeccable` skill plus root `PRODUCT.md` and `DESIGN.md`; use its operate-mode guidance without allowing the skill to expand this rule or the trusted task. If its context launcher is denied, follow the skill's documented fallback and read the committed context directly.
- Edit only the exact `admin/src/features/<task>/**` paths named by the trusted task, including new, committed, staged, unstaged, and untracked files.
- Keep the Codex-owned app, theme mechanism, API client, auth, domain, ports, data, generated types/fixtures, routing, shared components, hooks, manifests, lockfiles, build/test configuration, Docker/nginx, CI, runner, rules, and gates unchanged.
- Use existing interfaces and injected props/callbacks/hooks only. Never call `fetch` directly, hardcode API results, invent balance or supplier state, add a dependency, disable a test, or enable a real purchase/payment/refund action.
- Implement only presentation components, visual hierarchy, layout, component-local styling, responsive behavior, light motion, and component-local interaction while preserving loading, error, empty, and success states. Keep the admin basic and task-focused in both themes; do not add a landing-page hero, 3D/neon treatment, heavy glass, or distracting looping motion.
- If the task needs an out-of-scope architecture, API, auth, business, dependency, or configuration change, return `BLOCKED` to the coordinator. Do not make the change and do not ask the owner to relay it.
- Do not create, delegate to, or resume a subagent, background agent, or second writer. This conversation is the only UI writer.
- The committed workspace `PreToolUse` hook hard-denies shell, background-task, scheduling, permission-escalation, and collaboration tools before execution. It intercepts writes to its hook, rules, handler, and command resolver as immutable. Do not try to bypass, disable, rename, or edit that guard or launch a nested `agy` process by any route.
- Report every denied shell-based check as `NOT_RUN`; the coordinator and CI run the existing checks after validating the bounded diff. Never claim a denied or unavailable check passed.
