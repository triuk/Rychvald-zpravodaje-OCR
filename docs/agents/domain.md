# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the project.

## Before exploring, read these

This repository uses a **single-context** layout:

- **`GLOSSARY.md`** at the repository root: project terminology.
- **`docs/adr/`**: read ADRs relevant to the area being explored.

If these files do not exist, proceed silently. The `/domain-modeling` skill creates them lazily when terms or decisions are resolved.

## File structure

```text
/
├── GLOSSARY.md
└── docs/
    └── adr/
        └── NNNN-short-decision-title.md
```

## Use the glossary's vocabulary

When naming a domain concept in an issue title, refactor proposal, hypothesis or test name, use the term defined in `GLOSSARY.md`.

If the concept is missing, check whether it belongs to the project's vocabulary. Note real terminology gaps for `/domain-modeling`.

## Flag ADR conflicts

If a proposal contradicts an existing ADR, name that ADR and explain why the decision should be reopened.
