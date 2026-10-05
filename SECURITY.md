# Security

## Reporting a vulnerability

Report privately through GitHub Security Advisories (Security tab -> "Report a
vulnerability"). Please do not open a public issue.

Include what you did, what happened, what you expected, and the commit you tested.
Expect an acknowledgement within 72 hours and an assessment within a week.

## Threat model

This service accepts untrusted free text and sends it to a model. In scope:

| Threat | Control | Where |
| --- | --- | --- |
| Credentials or PII reaching prompts, the vector store or logs | redaction of emails, phone numbers, card-like numbers, cloud access keys and bearer tokens before anything leaves the process | `ai/guardrails.py` |
| Prompt injection from input or retrieved content | pattern screening, fails closed | `ai/guardrails.py` |
| Oversized or malformed input | length, empty and control-character checks | `ai/guardrails.py` |
| Runaway model spend | per-request token metering and an optional budget ceiling | `ai/costs.py` |
| Credential exposure | every secret is read from the environment; `.env` is git-ignored | `ai/config.py` |

Explicitly **out of scope**:

- Pattern-based injection screening is a heuristic. It narrows the attack surface;
  it does not close it. Retrieved content is untrusted input too.
- Redaction is pattern-based. It catches the common shapes of a secret, not every one.

## Handling secrets

Never commit `.env`. If a credential is committed, treat it as compromised:
rotate it first, then remove it from the tree. Deleting the file without rotating
the secret fixes nothing, because history keeps a copy.

## Supported versions

`main` is the supported version.