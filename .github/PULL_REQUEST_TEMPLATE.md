## Summary

<!-- What does this PR do? Keep it short. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Agent improvement
- [ ] New agent proposal
- [ ] Documentation
- [ ] Installer / scripts
- [ ] Other (describe below)

## Agent(s) affected

<!-- Which agents does this touch? List them, or "none" if it's docs/scripts only. -->

## How to test

<!-- Steps to verify this works. Be specific. -->

1.
2.
3.

## Checklist

- [ ] I have read the [Contributing Guide](CONTRIBUTING.md)
- [ ] Agent files are written in English
- [ ] Trigger phrases include at least English and Italian
- [ ] New/modified agents follow the source frontmatter format (`name`, `description`, `capabilities`, `model`)
- [ ] Inter-agent messaging protocol is respected (if applicable)
- [ ] I have tested this with at least one platform (`bash scripts/build.sh --platform claude-code`)

---

## Compliance and Safety Declaration

> **This section is mandatory. Pull requests that do not satisfy every requirement below will be closed without review, regardless of code quality or intent.**

### Legal Compliance

By submitting this pull request, I declare that my changes:

- [ ] **Do not violate any applicable law or regulation**, including but not limited to:
  - The EU General Data Protection Regulation (GDPR), Regulation (EU) 2016/679
  - The California Consumer Privacy Act (CCPA), Cal. Civ. Code 1798.100 et seq.
  - The UK Data Protection Act 2018
  - Any other national, regional, or sector-specific data protection, consumer protection, intellectual property, or privacy legislation applicable in any jurisdiction where this software may be used
- [ ] **Do not introduce any mechanism** that collects, transmits, stores, or processes personal data of users or third parties beyond the user's local filesystem
- [ ] **Do not circumvent, weaken, or remove** any existing privacy safeguard, disclaimer, or data protection notice present in the codebase

### Health, Medical, and Psychological Safety

**LLMs are stochastic systems. They produce probabilistic output that can be incorrect, misleading, incomplete, or harmful.**

By submitting this pull request, I declare that my changes:

- [ ] **Do not remove, weaken, or circumvent existing disclaimers** that inform users of the non-professional nature of agent output
- [ ] **Include appropriate disclaimers** in any new or modified agent, clearly stating that the agent's output is AI-generated and not validated by any authority

### Acknowledgment

- [ ] I have read and understood the project's [Terms of Use](TERMS_OF_USE.md) and [Disclaimers](docs/DISCLAIMERS.md)
- [ ] I understand that this project may be used by vulnerable individuals and that contributor responsibility extends beyond code correctness to the real-world impact of agent behavior
---

> **Note to contributors:** This policy exists because this project reaches users who may be in vulnerable states. Every contribution must preserve safety boundaries. If you are unsure whether your changes comply, open a Discussion issue first. When in doubt, err on the side of caution. See [TERMS_OF_USE.md](TERMS_OF_USE.md) for the full legal framework.
