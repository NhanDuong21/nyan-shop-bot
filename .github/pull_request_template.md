## Linked work

- Issue URL:
- Dependency URLs:
- Owner role / claim:
- Base SHA:
- Head SHA:

## Scope

- In scope:
- Explicitly out of scope:
- Files/modules owned by this writer:

## Evidence

- [ ] `python scripts/task.py verify`
- [ ] `python scripts/task.py smoke`
- [ ] GitHub Actions `ci-gate` (link after the run exists)
- [ ] No test/result above is claimed PASS unless it actually ran on this HEAD

## Safety review

- [ ] Defaults remain `SUPPLIER_MODE=mock`, `PAYMENT_MODE=disabled`, `ALLOW_REAL_PURCHASES=false`
- [ ] No live purchase/top-up/refund/delivery/Telegram transport was called
- [ ] No credential, partner source document, `.env`, or local data is tracked/logged/artifacted
- [ ] Admin remains localhost-only until authentication and staging ingress are approved
- [ ] Workflow changes keep PR permissions read-only and Actions pinned to full SHAs

## Reviewer handoff

Review this exact HEAD against the linked issue. Lead with correctness/security/test findings and leave COMMENT only; Nyan decides whether to merge.
