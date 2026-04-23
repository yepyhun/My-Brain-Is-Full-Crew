# Runtime Hardening Reference Pack

This folder contains a sanitized reference pack of vault runtime hardening components.

What is included:

- deterministic guard and audit scripts for daily continuity, temporal reminders, source retention, and backlog hygiene
- a post-turn orchestration example that stitches those runtimes together
- focused regression tests using generic fixtures

What is intentionally excluded:

- personal vault content
- live state files from `Meta/Operational/` or `Meta/states/`
- email transport helpers, contact details, and local launch scripts
- repo-local hooks and machine-specific config

Expected layout:

- these scripts assume a vault-like root with folders such as `07-Daily/`, `Meta/Operational/`, and `Meta/Temporal/Events/`
- many test cases create temporary roots and patch the module root explicitly, so the pack can be studied and exercised without a real vault

Run the reference tests:

```bash
python3 -m unittest discover -s references/runtime-hardening/tests -v
```

Notes:

- this is a reference export, not a drop-in public product surface
- the goal is to preserve reusable hardening patterns without leaking personal data or noisy local artifacts
