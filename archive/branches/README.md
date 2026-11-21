# Archived branches

These snapshots preserve changed files from retired Millennium Dawn branches,
not full Git history or complete branches. Each copy keeps the file's path
within the original repo.

## Layout

- `<folder>/<repo-path>`: original branch file
- `<folder>/<folder>.json`: source branch name, tip commit, last author, last
  commit date, and archived file count

For the November 2026 snapshots, the metadata also records the `main` commit,
merge base, and paths deleted by the source branch. Files are selected from
changes since the merge base. `.gitignore` and files already identical on
`main` are omitted. A slash in a branch name becomes `--` in the folder name.

## Branches archived

| Branch                     | Last activity | Diverging files |
|----------------------------|---------------|------------------|
| yemen-development          | 2024-11-20    | 171              |
| Taiwan-dev                 | 2025-09-22    | 3                |
| ASEAN_shared_tree          | 2025-05-22    | 87 (583 nominal) |
| religion-breakdown-chart   | 2025-03-07    | 6                |
| panama-focuses             | 2025-10-13    | 75               |
| danubia                    | 2025-02-17    | 27               |
| iraqi-gui                  | 2025-10-06    | 20               |
| military-strength          | 2025-11-06    | 1                |
| 3D-tank-models-to-check    | 2025-12-13    | 113              |
| didi                       | 2025-11-28    | 146              |
| Irish-Development          | 2025-12-23    | 107              |
| import-venezuela-import-fork  | 2026-02-21    | 23               |
| kurdistan-development         | 2026-06-23    | 8                |
| lebanon-development           | 2026-05-13    | 6                |
| mexican-development           | 2026-05-17    | 67               |
| palestine_development         | 2024-12-03    | 4                |

ASEAN_shared_tree shows 583 in the 3-dot diff but 496 of those files are
byte-identical to main; only 87 actually differ. The script's identical-skip
filter handles this. didi has 2 files identical to main for the same reason.

yemen-development's `MD_focus_​HOU_l_english.yml` has a zero-width space in
its filename, which `git diff --name-only` quotes and our normal path loop
drops. It is recovered out-of-band via the script's post-step.

## November 2026 snapshots

| Branch | Last activity | Archived files |
| --- | --- | ---: |
| `feat/internal-faction-opinion-decisions-459` | 2026-09-23 | 45 |
| `md-railway-guns` | 2026-10-29 | 11 |
| `chad-overhaul` | 2026-09-15 | 108 |
| `feature/government-workforce` | 2026-10-21 | 8 |
| `australian-content-old` | 2026-08-11 | 93 |
| `isis-development` | 2026-10-21 | 24 |
| `morocco-development` | 2026-07-12 | 15 |
| `corporations-and-companies` | 2026-05-19 | 142 |
| `tanzania-development` | 2026-10-21 | 91 |
| `usoe-rework` | 2026-10-08 | 143 |
| `uk-gui-work` | 2026-06-23 | 9 |
| `tst-ter-org` | 2026-06-17 | 3 |
| `malawian-development` | 2026-08-17 | 137 |
| `tutorial-dev2` | 2026-09-05 | 14 |
| `let-me-try-sum` | 2026-06-15 | 51 |
| `tunisia-development` | 2026-03-25 | 4 |
| `take-two-uk-hoc` | 2026-03-17 | 11 |
| `menu-visual-edit` | 2026-02-23 | 9 |
