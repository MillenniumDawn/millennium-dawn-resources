# millennium-dawn-resources

Holding ground for non-essential resources migrated out of the main
[Millennium-Dawn](https://github.com/MillenniumDawn/Millennium-Dawn) repository:
helper scripts, ops tooling, audit reports, and anything else that doesn't ship
inside the mod itself.

## Layout

```
scripts/                 Operational and audit scripts (Python, shell, ...)
.pre-commit-config.yaml  Shared lint config — mirrors MD repo versions
.secrets.baseline        detect-secrets baseline
```

## Scripts

### `scripts/find_unassigned.py`

Reports who needs work assigned on a Millennium Dawn org project:

1. Open project items (issues / PRs) with no assignee.
2. Team members with zero project items assigned to them.
3. Project assignees who are not on the team.

Uses the `gh` CLI for authentication — no hand-managed PAT.

```bash
# explicit
python3 scripts/find_unassigned.py --org MillenniumDawn --team team-members --project 1

# via env vars
MD_TEAM=team-members MD_PROJECT=1 python3 scripts/find_unassigned.py

# machine-readable
python3 scripts/find_unassigned.py --team team-members --project 1 --json > report.json
```

#### Required `gh` scopes

| Scope          | Used for                                    |
| -------------- | ------------------------------------------- |
| `read:org`     | Listing org team membership                 |
| `read:project` | Reading ProjectV2 board items and assignees |

Minimum auth setup. `gh auth refresh -s` is **additive** — it adds the listed
scopes to your token without revoking any scopes you already have:

```bash
gh auth login                            # one-time, if not already logged in
gh auth refresh -s read:org,read:project # adds these; existing scopes preserved
gh auth status                           # verify all scopes are present
```

`repo` scope is **not** required for this script — it only reads org/team and
project metadata, no repository contents. If you already have `repo` from
other workflows it will remain after the refresh.

## Linting

This repo enforces the same code-style baseline as the main Millennium-Dawn
repo via [pre-commit](https://pre-commit.com).

```bash
pip install pre-commit
pre-commit install                       # run on every git commit
pre-commit run --all-files               # one-off full pass
pre-commit run --files path/to/file      # scope to specific files
```

Hook coverage:

- **detect-secrets** — leaked credentials (baseline at `.secrets.baseline`)
- **pre-commit-hooks** — whitespace, line endings, JSON/YAML/TOML syntax,
  large-file guard, merge-conflict markers, shebang/executability checks,
  Python AST + `debug-statements`
- **black** + **isort** + **ruff** — Python formatting and linting
- **shellcheck** — shell script linting
- **prettier** — Markdown formatting

Versions track the main MD repo's `.pre-commit-config.yaml` to keep behaviour
consistent across both repositories.
