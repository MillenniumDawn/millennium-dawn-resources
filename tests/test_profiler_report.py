import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts import profiler_report as profiler


def scope(duration, entry=None, **children):
    node = {"duration": duration, **children}
    if entry is not None:
        node["entry"] = entry
    return node


class ProfilerTests(unittest.TestCase):
    def table(self, report, title):
        return dict(report["tables"])[title]

    def test_parallel_timings_and_nested_name(self):
        tree = scope(
            34052683973,
            type=0,
            **{
                "0_non_assigned": scope(34052683973, 0, **{"1_real_child": scope(12, 1)}),
                "2_gamestate.hourly": scope(17657476109, 361),
                "3_ai_update": scope(
                    5626989154,
                    361,
                    num_threads=23,
                    profiled=1223,
                    **{"4_CAICore.update_parallel": scope(65961764188, 81961)},
                ),
                "5_gamestate.weekly": scope(
                    295604157,
                    2,
                    **{
                        "6_ingame_update_setup": scope(
                            221012979,
                            2,
                            **{"7_ingame_update_setup": scope(220984791, 2)},
                        )
                    },
                ),
            },
        )
        report = profiler.analyze(tree, 20)
        names = {row[0]: row for row in self.table(report, "Top aggregate names")}
        self.assertEqual(names["ingame_update_setup"][1:5], ["221.012979", "2", "110.506490", "1"])
        self.assertEqual(names["CAICore.update_parallel"][1:3], ["65961.764188", "81961"])
        self.assertNotIn("non_assigned", names)
        self.assertIn("real_child", names)
        sections = {row[0]: row for row in self.table(report, "Recorded top-level sections")}
        self.assertEqual(sections["ai_update"][1:3], ["5626.989154", "361"])
        self.assertEqual(sections["ai_update"][5], "23")
        paths = self.table(report, "Top individual paths (overlapping)")
        self.assertTrue(
            any("6_ingame_update_setup > 7_ingame_update_setup" in row[0] for row in paths)
        )
        self.assertTrue(any("accumulated parallel worker time" in note for note in report["notes"]))
        self.assertIn("34052.683973 ms", report["notes"][0])

    def test_leaf_mirror_counts_and_tolerance(self):
        for section_count, leaf_count, delta, suppressed in [
            (361, 361, 0, True),
            (361, 361, 1, True),
            (361, 361, -1, True),
            (361, 361, 2, False),
            (361, 360, 0, False),
            (None, None, 0, True),
            (None, 1, 0, False),
            (1, None, 0, False),
            (0, 0, 0, True),
        ]:
            with self.subTest(section=section_count, leaf=leaf_count, delta=delta):
                tree = scope(
                    2000,
                    type=0,
                    **{
                        "0_non_assigned": scope(
                            2000,
                            0,
                            **{
                                "1_hourly": scope(1000 + delta, leaf_count),
                                "2_real": scope(10, 1),
                            },
                        ),
                        "3_hourly": scope(1000, section_count),
                    },
                )
                report = profiler.analyze(tree, 20)
                rows = {row[0]: row for row in self.table(report, "Top aggregate names")}
                self.assertEqual(
                    rows["hourly"][1], profiler.ms(1000 if suppressed else 2000 + delta)
                )
                self.assertEqual(rows["hourly"][4], "1" if suppressed else "2")
                self.assertIn("real", rows)
                paths = self.table(report, "Top individual paths (overlapping)")
                self.assertEqual(any("1_hourly" in row[0] for row in paths), not suppressed)

    def test_matching_scopes_outside_wrapper_children_are_retained(self):
        tree = scope(
            3000,
            type=0,
            **{
                "0_hourly": scope(1000, 2),
                "1_other": scope(1000, 2, **{"2_hourly": scope(1000, 2)}),
                "3_non_assigned": scope(
                    3000,
                    **{
                        "4_wrapper": scope(1000, 2, **{"5_hourly": scope(1000, 2)}),
                    },
                ),
            },
        )
        report = profiler.analyze(tree)
        names = {row[0]: row for row in self.table(report, "Top aggregate names")}
        self.assertEqual(names["hourly"][1:5], ["0.003000", "6", "0.000500", "3"])
        paths = {row[0] for row in self.table(report, "Top individual paths (overlapping)")}
        self.assertIn("1_other > 2_hourly", paths)
        self.assertIn("3_non_assigned > 4_wrapper > 5_hourly", paths)
        self.assertIn("Suppressed 0 leaf mirrors", report["notes"][1])

    def test_nonleaf_section_copy_is_not_suppressed(self):
        tree = scope(
            2000,
            type=0,
            **{
                "0_non_assigned": scope(
                    2000,
                    0,
                    **{
                        "1_hourly": scope(1000, 2, **{"2_actual": scope(20, 1)}),
                    },
                ),
                "3_hourly": scope(1000, 2),
            },
        )
        report = profiler.analyze(tree, 20)
        names = {row[0]: row for row in self.table(report, "Top aggregate names")}
        self.assertEqual(names["hourly"][1:3], ["0.002000", "4"])
        self.assertIn("actual", names)
        self.assertIn("Suppressed 0 leaf mirrors", report["notes"][1])

    def test_nested_names_across_other_callers(self):
        tree = scope(
            100,
            type=0,
            **{
                "0_work_effect": scope(
                    80,
                    8,
                    **{
                        "1_wrapper": scope(80, 8, **{"2_work_effect": scope(80, 8)}),
                    },
                ),
                "3_other": scope(20, 2, **{"4_work_effect": scope(10, 1)}),
            },
        )
        report = profiler.analyze(tree, 20)
        names = {row[0]: row for row in self.table(report, "Top aggregate names")}
        self.assertEqual(names["work_effect"][1:5], ["0.000090", "9", "0.000010", "2"])
        for title in [
            "Top individual paths (overlapping)",
            "Script candidate paths (overlapping)",
        ]:
            paths = {row[0] for row in self.table(report, title)}
            self.assertIn("0_work_effect", paths)
            self.assertIn("0_work_effect > 1_wrapper > 2_work_effect", paths)
        self.assertIn("Suppressed 0 leaf mirrors and 1 nested same-name", report["notes"][1])

    def test_unknown_aggregate_count(self):
        tree = scope(
            100,
            type=0,
            **{
                "0_parent": scope(
                    90,
                    1,
                    **{
                        "1_item": scope(10),
                        "2_item": scope(20, 3),
                        "3_zero": scope(0, 0),
                    },
                ),
            },
        )
        names = {
            row[0]: row for row in self.table(profiler.analyze(tree, 20), "Top aggregate names")
        }
        self.assertEqual(names["item"][1:5], ["0.000030", "unknown", "undefined", "2"])
        self.assertEqual(names["zero"][2:4], ["0", "undefined"])

    def test_rankings_bounded_and_scripts_separate(self):
        tree = scope(
            10000,
            type=0,
            **{
                "0_engine": scope(
                    9999,
                    1,
                    **{
                        **{
                            f"{index}_wrapper_{index}": scope(1000 + index, 1)
                            for index in range(100)
                        },
                        "101_common/on_actions/test.txt:17": scope(50, 2),
                        "102_named_effect": scope(40, 1),
                    },
                ),
            },
        )
        report = profiler.analyze(tree, 2)
        for title, rows in report["tables"]:
            if title != "Recorded top-level sections":
                self.assertLessEqual(len(rows), 2)
        scripts = self.table(report, "Script candidates (label heuristic)")
        self.assertEqual(
            [row[0] for row in scripts],
            ["common/on_actions/test.txt:17", "named_effect"],
        )
        paths = self.table(report, "Script candidate paths (overlapping)")
        self.assertEqual(paths[0][0], "0_engine > 101_common/on_actions/test.txt:17")
        self.assertLess(len(profiler.html_report(report)), 20000)

    def test_decision_candidates_ranked_separately(self):
        suffixes = [
            "available",
            "allowed",
            "should_show",
            "is_valid_target",
            "is_valid_root",
            "options",
        ]
        children = {
            f"{index}_decision_{suffix}": scope(100 - index, 1)
            for index, suffix in enumerate(suffixes)
        }
        tree = scope(
            10000,
            type=0,
            **{"0_CAIPoliticalMinister": scope(9999, 1, **children)},
        )
        report = profiler.analyze(tree, 6)
        scripts = self.table(report, "Script candidates (label heuristic)")
        self.assertEqual([row[0] for row in scripts], [f"decision_{suffix}" for suffix in suffixes])
        paths = self.table(report, "Script candidate paths (overlapping)")
        self.assertEqual(
            [row[0] for row in paths],
            [f"0_CAIPoliticalMinister > {key}" for key in children],
        )
        self.assertIn("decision_available", report["notes"][4])

    def test_normalization(self):
        self.assertEqual(profiler.normalize("123_foo_42_effect"), "foo_42_effect")
        for name in ["foo_42", "12foo", "_foo", "foo/bar.txt:17"]:
            self.assertEqual(profiler.normalize(name), name)

    def test_bad_shapes_and_metrics(self):
        for node in [
            [],
            None,
            {},
            {"duration": 1, "child": []},
            {"duration": True},
            {"duration": "1"},
            {"duration": -1},
            {"duration": float("nan")},
            {"duration": float("inf")},
            {"duration": 1, "entry": -1},
            {"duration": 1, "entry": 1.5},
            {"duration": 1, "entry": None},
            {"duration": 1, "num_threads": 0},
            {"duration": 1, "num_threads": 1.2},
            {"duration": 1, "profiled": "62"},
        ]:
            with self.subTest(node=node), self.assertRaises(ValueError):
                profiler.validate(node, "test")
        self.assertEqual(profiler.validate(scope(1, 0, profiled=1223), "test"), 0)

    def test_units_and_unknown_counts(self):
        self.assertEqual(profiler.ms(34052683973), "34052.683973")
        self.assertEqual(
            profiler.cells("test", 2_000_000, 2, 1)[1:4], ["2.000000", "2", "1.000000"]
        )
        self.assertEqual(profiler.cells("test", 1, None, 1)[2:4], ["unknown", "undefined"])
        self.assertEqual(profiler.cells("test", 1, 0, 1)[2:4], ["0", "undefined"])

    def test_output_escaping(self):
        label = "</script><img src=x onerror=alert(1)>|[x](javascript:bad)\n`*\x11&"
        report = {
            "notes": [label],
            "tables": [("Example", [profiler.cells(label, 1, 1, 1)])],
        }
        page = profiler.html_report(report)
        text = profiler.markdown(report)
        self.assertNotIn("<img", page)
        self.assertNotIn("<img", text)
        self.assertEqual(page.count("</script>"), 1)
        self.assertIn("&lt;img", page)
        self.assertIn(r"\[x\]\(javascript:bad\)", text)
        self.assertIn(r"\|", text)
        self.assertNotIn("\x11", page + text)
        self.assertIn(r"\u0011", page)
        self.assertIn("addEventListener('input'", page)
        self.assertIn("addEventListener('click'", page)
        self.assertNotIn("fetch(", page)
        self.assertNotIn("innerHTML", page)

    def test_script_labels(self):
        for label in [
            "common/on_actions/a.txt:614",
            r"common\effects\a.txt",
            "a_effect",
            "a_effects",
            "a_trigger",
            "a_triggers",
            "a_available",
            "a_allowed",
            "a_should_show",
            "a_is_valid_target",
            "a_is_valid_root",
            "a_options",
        ]:
            self.assertIsNotNone(profiler.SCRIPT.search(label), label)
        for label in [
            "CAICore.update_parallel",
            "custom_trigger_tooltip",
            "effect",
            "42_and",
        ]:
            self.assertIsNone(profiler.SCRIPT.search(label), label)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.log = self.root / "capture.log"
        self.original = (
            '\ufeff{"type":0,"duration":1000000,"0_bad\u0011_label":{"duration":500000,"entry":2}}'
        )
        self.log.write_text(self.original, encoding="utf-8")

    def run_cli(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = profiler.main([str(self.log), *map(str, arguments)])
        return result, out.getvalue(), err.getvalue()

    def test_stdout_and_artifacts(self):
        result, text, error = self.run_cli()
        self.assertEqual((result, error), (0, ""))
        self.assertIn("# HOI4 profiler report", text)
        self.assertIn("1.000000 ms", text)
        page, report = self.root / "nested" / "report.html", self.root / "report.md"
        result, text, error = self.run_cli("--html", page, "--markdown", report, "--top", 1)
        self.assertEqual((result, text, error), (0, "", ""))
        self.assertIn("<!doctype html>", page.read_text())
        self.assertIn("# HOI4 profiler report", report.read_text())
        self.assertEqual(self.log.read_text(encoding="utf-8"), self.original)

    def test_collisions(self):
        symlink, hardlink = self.root / "sym.log", self.root / "hard.log"
        symlink.symlink_to(self.log)
        os.link(self.log, hardlink)
        for alias in [self.log, self.root / "." / "capture.log", symlink, hardlink]:
            with self.subTest(alias=alias):
                result, _, error = self.run_cli("--html", alias)
                self.assertEqual(result, 2)
                self.assertIn("distinct", error)
                self.assertEqual(self.log.read_text(encoding="utf-8"), self.original)
        output = self.root / "output"
        result, _, error = self.run_cli("--html", output, "--markdown", output)
        self.assertEqual(result, 2)
        self.assertIn("distinct", error)
        self.assertFalse(output.exists())
        output.write_text("untouched")
        alias = self.root / "output-alias"
        os.link(output, alias)
        result, _, _ = self.run_cli("--html", output, "--markdown", alias)
        self.assertEqual(result, 2)
        self.assertEqual(output.read_text(), "untouched")

    def test_friendly_errors(self):
        for payload in [
            "not JSON",
            "[]",
            '{"type":0,"duration":1,"child":[]}',
            '{"type":0,"duration":NaN}',
            '{"type":0,"duration":1,"c":{"entry":2}}',
        ]:
            with self.subTest(payload=payload):
                self.log.write_text(payload)
                result, _, error = self.run_cli()
                self.assertEqual(result, 2)
                self.assertIn("profiler_report: error:", error)
                self.assertNotIn("Traceback", error)
        self.log.write_bytes(b"\xff")
        self.assertEqual(self.run_cli()[0], 2)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(profiler.main([str(self.root / "missing")]), 2)

    def test_capture_root_requirements_are_friendly(self):
        for payload, message in [
            ({"duration": 1, "c": scope(1)}, "capture must have type 0"),
            ({"type": 1, "duration": 1, "c": scope(1)}, "capture must have type 0"),
            ({"type": True, "duration": 1, "c": scope(1)}, "type must be"),
            ({"type": False, "duration": 1, "c": scope(1)}, "type must be"),
            ({"type": 0.0, "duration": 1, "c": scope(1)}, "type must be an integer"),
            ({"type": 0, "c": scope(1)}, "expected an object with duration"),
            (
                {"type": 0, "duration": 1},
                "capture must contain at least one child scope",
            ),
        ]:
            with self.subTest(payload=payload):
                self.log.write_text(json.dumps(payload))
                result, text, error = self.run_cli()
                self.assertEqual((result, text), (2, ""))
                self.assertIn("profiler_report: error:", error)
                self.assertIn(message, error)
                self.assertNotIn("Traceback", error)

    def test_top_must_be_positive(self):
        for value in ["0", "-1", "1.2", "oops"]:
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    self.run_cli("--top", value)
                self.assertEqual(raised.exception.code, 2)

    def test_numeric_overflow_is_friendly(self):
        self.log.write_text(
            json.dumps(
                scope(
                    1e308,
                    type=0,
                    **{
                        "0_parent": scope(
                            1e308,
                            **{
                                "1_item": scope(1e308),
                                "2_item": scope(1e308),
                            },
                        ),
                    },
                )
            )
        )
        result, _, error = self.run_cli()
        self.assertEqual(result, 2)
        self.assertIn("numeric range", error)
        self.assertNotIn("Traceback", error)

    def test_malformed_input_does_not_write(self):
        self.log.write_text(json.dumps({"type": 0, "duration": 1, "child": {"duration": -1}}))
        output = self.root / "output.md"
        output.write_text("untouched")
        self.assertEqual(self.run_cli("--markdown", output)[0], 2)
        self.assertEqual(output.read_text(), "untouched")


if __name__ == "__main__":
    unittest.main()
