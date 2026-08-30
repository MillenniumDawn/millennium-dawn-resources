# millennium-dawn-resources

Holding ground for non-essential resources migrated out of the main
[Millennium-Dawn](https://github.com/MillenniumDawn/Millennium-Dawn) repository:
helper scripts, ops tooling, audit reports, and anything else that doesn't ship
inside the mod itself.

## Layout

```
archive/                 Material retired from the mod repo (see below)
scripts/                 Operational and audit scripts (Python, shell, ...)
scripts/legacy/          Unmaintained scripts, kept verbatim
.pre-commit-config.yaml  Shared lint config — mirrors MD repo versions
.secrets.baseline        detect-secrets baseline
```

## Archive

`archive/` is where content leaves the mod repo when it is no longer worth
carrying there but is worth keeping. Nothing in it is maintained, nothing in it
is expected to compile, and the lint hooks skip it entirely so that raw HOI4
files keep their original BOMs and line endings.

| Directory                | Contents                                                                                  |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| `archive/branches/`      | Diverging files from 12 stale upstream branches, one directory per branch                 |
| `archive/content/`       | Cut and never-integrated country content, including the Dread submods and Wagner          |
| `archive/systems/`       | Cut or prototype game systems: space, trade, internal factions, officer corps, and more   |
| `archive/oobs/`          | Order-of-battle source material, mostly Military Balance PDFs and spreadsheets            |
| `archive/gfx-templates/` | Layered source files (psd/psb/ai) for mod graphics                                        |
| `archive/spreadsheets/`  | Balance and economy workbooks                                                             |
| `archive/reference/`     | Loose reference: world map, state category cheat sheet, subideology guides, editor syntax |

### Regenerating `archive/branches/`

The generator still lives in the mod repo, because it reads that repo's branch
refs. Point it here:

```bash
cd /path/to/Millennium-Dawn
python3 tools/archive_stale_branches.py --output ../millennium-dawn-resources/archive/branches
```

It defaults to that path already, so a plain run works when the two checkouts
are siblings.

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

### `scripts/last_commit.py`

Reports the most recent commit per user, org-wide (or for a single user, or
scoped to one repo). Pairs with `find_unassigned.py` to spot members who are
idle on both assignments **and** commits.

```bash
# one user
python3 scripts/last_commit.py --user AngriestBird

# every member of a team, stalest first
python3 scripts/last_commit.py --team team-members

# scoped to one repo
python3 scripts/last_commit.py --user AngriestBird --repo MillenniumDawn/Millennium-Dawn

# machine-readable
python3 scripts/last_commit.py --team team-members --json > activity.json
```

Same `gh` auth as `find_unassigned.py` — `read:org` (for `--team`) is enough;
`read:project` is **not** required.

The script merges two signals to avoid the search/commits API's default-branch
blind spot:

- `search/commits` — lifetime data, but only indexes commits on each repo's
  default branch.
- `users/{u}/events/public` — public PushEvents on any branch, last ~90 days
  / 300 events.

The more recent of the two wins per user, so feature-branch work in an open
or unmerged branch still shows up.

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
