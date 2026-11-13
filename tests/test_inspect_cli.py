# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - tests/test_inspect_cli.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The inspector of a machine.xml answers JSON by default, text with --text, and its exit codes are the documented ones."""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XML = (
    '<openpnp-machine><machine class="ReferenceMachine"><head/><camera/><camera/><driver/><feeder/><feeder/>'
    "<actuators><actuator/></actuators><nozzle-tips><nozzle-tip/></nozzle-tips></machine></openpnp-machine>"
)


def load():
    spec = importlib.util.spec_from_file_location("inspect_openpnp_config_under_test", ROOT / "tools" / "inspect_openpnp_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*arguments):
    tool = load()
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["inspect_openpnp_config.py", *arguments]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = tool.main()
            except SystemExit as stop:
                code = stop.code
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


class InspectCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.good = Path(self._tmp.name) / "machine.xml"
        self.good.write_text(XML, encoding="utf-8")

    def test_json_is_the_default(self):
        code, out, _ = run("--config", str(self.good))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["available"])
        self.assertEqual((data["machine_class"], data["head_count"], data["camera_count"]), ("ReferenceMachine", 1, 2))

    def test_text_is_the_summary_for_a_person(self):
        code, out, _ = run("--config", str(self.good), "--text")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("OPENPNP_PROFILE=PASS"))
        self.assertNotIn("{", out)

    def test_the_old_json_flag_still_works_and_changes_nothing(self):
        self.assertEqual(run("--config", str(self.good), "--json")[1], run("--config", str(self.good))[1])

    def test_json_and_text_together_are_refused_with_exit_code_two(self):
        code, _, err = run("--config", str(self.good), "--json", "--text")
        self.assertEqual(code, 2)
        self.assertIn("cannot be used together", err)

    def test_a_file_that_cannot_be_read_exits_one_in_both_forms_and_the_json_says_why(self):
        missing = str(Path(self._tmp.name) / "none.xml")
        code, out, _ = run("--config", missing)
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertFalse(data["available"])
        self.assertTrue(data["reason"])
        code, out, _ = run("--config", missing, "--text")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("OPENPNP_PROFILE=FAIL"))

    def test_the_launchers_keep_the_text_for_a_person(self):
        self.assertIn("--text", (ROOT / "inspect-openpnp-config.sh").read_text(encoding="utf-8"))
        self.assertIn("--text", (ROOT / "inspect-openpnp-config.bat").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
