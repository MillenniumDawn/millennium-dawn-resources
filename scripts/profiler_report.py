import argparse
import heapq
import html
import json
import math
import re
import sys
from pathlib import Path

METRICS = {
    "type",
    "start",
    "duration",
    "duration_in_ms",
    "entry",
    "profiled",
    "num_threads",
}
PREFIX = re.compile(r"^[0-9]+_")
SCRIPT = re.compile(
    r"(?:[/\\].*\.txt(?::[0-9]+)?$|_"
    r"(?:effects?|triggers?|available|allowed|should_show|is_valid_target|is_valid_root|options)$)"
)
CAVEATS = [
    "Durations are recorded inclusive time in milliseconds, not self time. Rows overlap; "
    "do not add sections, names, or paths together.",
    "Capture elapsed time, top-level scope durations, and accumulated parallel worker time "
    "are different measures. Threaded children may exceed their parent or the entire capture. "
    "No child-sum subtraction or capture percentages are used.",
    "Missing entries are unknown, not zero or one. Averages are undefined for unknown or zero "
    "entries. An aggregate count is unknown if any contributing count is unknown.",
    "Names lose only a leading numeric underscore prefix. Nested occurrences of the same name "
    "are excluded from that name's inclusive sum and calls, but remain in individual paths.",
    "Leaf mirrors of top-level sections are omitted only from immediate children of the "
    "top-level non_assigned wrapper when names match, durations differ by at most 1 ns, "
    "and entry counts match (including both unknown). The wrapper is not ranked; "
    "its real children are retained. Same-name scopes in other sections are retained and "
    "may be cross-section aliases, so name totals are neither elapsed time nor additive.",
    "Script candidates use a label heuristic: a source path ending in .txt (optional line "
    "number), or a name ending in _effect, _effects, _trigger, _triggers, _available, "
    "_allowed, _should_show, _is_valid_target, _is_valid_root, or _options. "
    "This is not proof that a label is a script or that it needs optimization.",
    "The profiled field is undocumented and is not interpreted. This capture has no "
    "per-call samples or percentiles and no comparison baseline. A short capture alone "
    "cannot establish an optimization benefit.",
]


def normalize(name):
    return PREFIX.sub("", name, count=1)


def validate(node, label):
    if not isinstance(node, dict) or "duration" not in node:
        raise ValueError(f"{label!r}: expected an object with duration")
    children = 0
    for key, value in node.items():
        if key not in METRICS:
            if not isinstance(value, dict):
                raise ValueError(f"{key!r}: expected a child scope object")
            children += 1
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label!r}: {key} must be a nonnegative finite number")
        if value < 0 or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError(f"{label!r}: {key} must be a nonnegative finite number")
        if key in {"entry", "num_threads", "type"} and not isinstance(value, int):
            raise ValueError(f"{label!r}: {key} must be an integer")
        if key == "num_threads" and value == 0:
            raise ValueError(f"{label!r}: num_threads must be positive")
    return children


def mirror_match(name, duration, entries, aliases):
    return any(
        abs(duration - other_duration) <= 1 and entries == other_entries
        for other_duration, other_entries in aliases.get(name, ())
    )


def analyze(root, top=20):
    if top < 1:
        raise ValueError("top must be positive")
    if not validate(root, "capture"):
        raise ValueError("capture must contain at least one child scope")
    if root.get("type") != 0:
        raise ValueError("capture must have type 0")
    sections, aliases = [], {}
    for key, node in root.items():
        if key in METRICS:
            continue
        validate(node, key)
        name = normalize(key)
        if name != "non_assigned":
            aliases.setdefault(name, []).append((node["duration"], node.get("entry")))
            sections.append((name, node["duration"], node.get("entry"), 1, node.get("num_threads")))

    aggregates, active = {}, {}
    paths, script_paths, ancestry = [], [], []
    stats = {"nodes": 0, "mirrors": 0, "nested": 0, "unknown": 0}

    def keep(heap, duration, entries, threads):
        if len(heap) < top or duration > heap[0][0]:
            item = (duration, stats["nodes"], " > ".join(ancestry), entries, threads)
            if len(heap) < top:
                heapq.heappush(heap, item)
            else:
                heapq.heapreplace(heap, item)

    def visit(key, node, threads):
        children = validate(node, key)
        name, duration, entries = normalize(key), node["duration"], node.get("entry")
        stats["nodes"] += 1
        stats["unknown"] += entries is None
        nested = bool(ancestry)
        mirror = (
            len(ancestry) == 1
            and normalize(ancestry[0]) == "non_assigned"
            and not children
            and mirror_match(name, duration, entries, aliases)
        )
        stats["mirrors"] += mirror
        ranked = not mirror and (nested or name != "non_assigned")
        ancestry.append(key)
        if ranked:
            keep(paths, duration, entries, threads)
            if SCRIPT.search(name):
                keep(script_paths, duration, entries, threads)
            if not active.get(name, 0):
                values = aggregates.get(name)
                if values is None:
                    aggregates[name] = [duration, entries, 1]
                else:
                    values[0] += duration
                    values[1] = (
                        None if entries is None or values[1] is None else values[1] + entries
                    )
                    values[2] += 1
            else:
                stats["nested"] += 1
            active[name] = active.get(name, 0) + 1
        for child_key, child in node.items():
            if child_key not in METRICS:
                visit(child_key, child, threads)
        if ranked:
            active[name] -= 1
            if not active[name]:
                del active[name]
        ancestry.pop()

    for key, node in root.items():
        if key not in METRICS:
            visit(key, node, node.get("num_threads"))

    names = heapq.nlargest(top, aggregates.items(), key=lambda item: item[1][0])
    scripts = heapq.nlargest(
        top,
        ((name, values) for name, values in aggregates.items() if SCRIPT.search(name)),
        key=lambda item: item[1][0],
    )
    sections.sort(key=lambda row: row[1], reverse=True)
    paths.sort(reverse=True)
    script_paths.sort(reverse=True)
    notes = [
        f"Capture elapsed: {ms(root['duration'])} ms.",
        f"Scanned {stats['nodes']} scopes; {len(aggregates)} ranked names. "
        f"Suppressed {stats['mirrors']} leaf mirrors and {stats['nested']} nested same-name "
        f"aggregate contributions. {stats['unknown']} scopes have unknown entry counts.",
        f"Rankings show at most {top} rows each; all {len(sections)} top-level sections are shown. "
        "Section threads are reported metadata, not a multiplier. Aggregate threads are unknown.",
    ]
    if sections:
        notes.append(
            f"Largest recorded top-level section: {sections[0][0]} "
            f"at {ms(sections[0][1])} ms (not an additive total)."
        )
    if scripts:
        name, values = scripts[0]
        notes.append(
            f"Largest script candidate by inclusive name time: {name}, "
            f"{ms(values[0])} ms across {values[2]} non-nested scopes. "
            "Inspect its caller paths and source before changing code."
        )
    else:
        notes.append("No script candidates matched the label heuristic.")
    if paths and paths[0][0] > root["duration"]:
        duration, _, path, _, threads = paths[0]
        notes.append(
            f"Largest individual scope: {path}, {ms(duration)} ms, exceeds capture elapsed. "
            f"Its section reports {threads if threads is not None else 'unknown'} threads. "
            "This can reflect accumulated parallel worker time, not elapsed capture time."
        )
    return {
        "notes": notes,
        "tables": [
            ("Recorded top-level sections", [cells(*row) for row in sections]),
            ("Top aggregate names", [cells(name, *values) for name, values in names]),
            (
                "Top individual paths (overlapping)",
                [
                    cells(path, duration, entries, 1, threads)
                    for duration, _, path, entries, threads in paths
                ],
            ),
            (
                "Script candidates (label heuristic)",
                [cells(name, *values) for name, values in scripts],
            ),
            (
                "Script candidate paths (overlapping)",
                [
                    cells(path, duration, entries, 1, threads)
                    for duration, _, path, entries, threads in script_paths
                ],
            ),
        ],
    }


def ms(value):
    if value is None:
        return "unknown"
    milliseconds = value / 1_000_000
    if not math.isfinite(milliseconds):
        raise ValueError("duration exceeds the supported numeric range")
    return f"{milliseconds:.6f}"


def cells(label, duration, entries, occurrences, threads=None):
    average = duration / entries if entries else None
    return [
        label,
        ms(duration),
        "unknown" if entries is None else str(entries),
        "undefined" if average is None else ms(average),
        str(occurrences),
        "unknown" if threads is None else str(threads),
    ]


def markdown_text(value):
    value = html.escape(display_text(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+!|~-])", r"\\\1", value)


def display_text(value):
    return "".join(f"\\u{ord(char):04x}" if ord(char) < 32 else char for char in str(value))


def markdown(report):
    lines = ["# HOI4 profiler report", ""]
    lines.extend(f"- {markdown_text(note)}" for note in report["notes"])
    for title, rows in report["tables"]:
        lines.extend(["", f"## {title}", ""])
        lines.append(
            "| Label / caller path | Inclusive ms | Entries | Mean ms/entry | Scopes | Section threads |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        lines.extend("| " + " | ".join(markdown_text(cell) for cell in row) + " |" for row in rows)
        if not rows:
            lines.append("| No matching scopes | | | | | |")
    lines.extend(["", "## Interpretation and limits", ""])
    lines.extend(f"- {markdown_text(note)}" for note in CAVEATS)
    return "\n".join(lines) + "\n"


STYLE = """
body{font:16px system-ui,sans-serif;margin:2rem;color:#202020;background:#fafafa}
table{border-collapse:collapse;width:100%;margin-bottom:2rem}th,td{padding:.45rem;
 border:1px solid #ccc;text-align:right}th:first-child,td:first-child{text-align:left;
 overflow-wrap:anywhere;max-width:65vw}th button{font:inherit;cursor:pointer}
input{font:inherit;padding:.5rem;width:90%;max-width:40rem}tr[hidden]{display:none}
"""
JAVASCRIPT = """
const search = document.querySelector('input');
search.addEventListener('input', () => {
  const query = search.value.toLowerCase();
  document.querySelectorAll('tbody tr').forEach(row => {
    row.hidden = !row.textContent.toLowerCase().includes(query);
  });
});
document.querySelectorAll('th button').forEach(button => {
  button.addEventListener('click', () => {
    const th = button.parentElement;
    const table = th.closest('table');
    const index = th.cellIndex;
    const ascending = th.getAttribute('aria-sort') !== 'ascending';
    table.querySelectorAll('th').forEach(header => header.removeAttribute('aria-sort'));
    th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
    const rows = Array.from(table.tBodies[0].rows);
    rows.sort((a, b) => {
      const x = a.cells[index].textContent, y = b.cells[index].textContent;
      const nx = Number(x), ny = Number(y);
      if (index && (!Number.isFinite(nx) || !Number.isFinite(ny))) {
        return Number(Number.isFinite(ny)) - Number(Number.isFinite(nx));
      }
      const order = index ? nx - ny : x.localeCompare(y);
      return ascending ? order : -order;
    });
    rows.forEach(row => table.tBodies[0].appendChild(row));
  });
});
"""


def html_report(report):
    def escape(value):
        return html.escape(display_text(value), quote=True)

    parts = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>HOI4 profiler report</title><style>{STYLE}</style><body>",
        "<h1>HOI4 profiler report</h1><ul>",
    ]
    parts.extend(f"<li>{escape(note)}</li>" for note in report["notes"])
    parts.extend(
        [
            '</ul><label>Search displayed rows <input type="search"></label>',
            "<p>Click a column heading to sort. Only the selected hottest rows are embedded.</p>",
        ]
    )
    headers = [
        "Label / caller path",
        "Inclusive ms",
        "Entries",
        "Mean ms/entry",
        "Scopes",
        "Section threads",
    ]
    for title, rows in report["tables"]:
        parts.append(f"<h2>{escape(title)}</h2><table><thead><tr>")
        parts.extend(f'<th><button type="button">{header}</button></th>' for header in headers)
        parts.append("</tr></thead><tbody>")
        for row in rows:
            parts.append("<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>")
        parts.append("</tbody></table>")
        if not rows:
            parts.append("<p>No matching scopes.</p>")
    parts.append("<h2>Interpretation and limits</h2><ul>")
    parts.extend(f"<li>{escape(note)}</li>" for note in CAVEATS)
    parts.append(f"</ul><script>{JAVASCRIPT}</script></body></html>\n")
    return "\n".join(parts)


def positive(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def check_paths(paths):
    for index, path in enumerate(paths):
        for other in paths[:index]:
            if path.resolve() == other.resolve() or (
                path.exists() and other.exists() and path.samefile(other)
            ):
                raise ValueError("input and output paths must be distinct, including aliases")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Summarize a HOI4 JSON profiler capture locally.")
    parser.add_argument("log", type=Path)
    parser.add_argument("--html", type=Path, help="write standalone searchable HTML")
    parser.add_argument("--markdown", type=Path, help="write Markdown instead of stdout")
    parser.add_argument("--top", type=positive, default=20, help="rows per ranking (default: 20)")
    args = parser.parse_args(argv)
    try:
        outputs = [path for path in (args.html, args.markdown) if path is not None]
        check_paths([args.log, *outputs])
        with args.log.open(encoding="utf-8-sig") as source:
            data = json.load(source, strict=False)
        report = analyze(data, args.top)
        del data
        for path, render in ((args.html, html_report), (args.markdown, markdown)):
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render(report), encoding="utf-8")
        if not outputs:
            print(markdown(report), end="")
    except (OSError, ValueError, RecursionError, OverflowError) as error:
        print(f"profiler_report: error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
