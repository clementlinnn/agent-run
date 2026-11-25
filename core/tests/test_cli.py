"""agent-run status 的输出（专用页面方案 §4.2、§5.3；只接 Claude Code 方案 §6）。"""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest

from agent_run import cli
from agent_run.cli import describe_window

NOW = 1794192000.0


class DescribeWindowTest(unittest.TestCase):
    def test_missing_and_no_limit(self):
        self.assertEqual(describe_window(None, NOW), "暂无数据")
        self.assertEqual(describe_window("none", NOW), "无此限额")

    def test_reset_countdown_units(self):
        self.assertEqual(describe_window({"used": 23.4, "resets_at": NOW + 30}, NOW), "23%（1 分钟后重置）")
        self.assertEqual(describe_window({"used": 5, "resets_at": NOW + 59 * 60}, NOW), "5%（59 分钟后重置）")
        self.assertEqual(describe_window({"used": 5, "resets_at": NOW + 135 * 60}, NOW), "5%（2 小时 15 分后重置）")
        self.assertEqual(describe_window({"used": 41, "resets_at": NOW + 3 * 86400 + 5 * 3600}, NOW),
                         "41%（3 天 5 小时后重置）")

    def test_passed_or_unknown_reset(self):
        self.assertEqual(describe_window({"used": 85, "resets_at": NOW - 1}, NOW), "0%（已重置）")
        self.assertEqual(describe_window({"used": 85, "resets_at": None}, NOW), "85%（重置时间未知）")



class StatusTest(unittest.TestCase):
    """status 只显示 Claude Code，并提示旧版留下的 Codex、dsh 残留。"""

    def setUp(self):
        self.user = tempfile.mkdtemp(prefix="user-")
        self.home = os.path.join(self.user, ".agent-run")
        os.makedirs(os.path.join(self.home, "run"))
        with open(os.path.join(self.home, "run", "status.json"), "w") as f:
            json.dump({"cc": 2, "cx": 0, "ds": 0, "done": 5, "wn": 0, "waiting": [],
                       "link": False, "updated": time.time(), "agents": {}}, f)
        self.saved_home = os.environ.get("HOME")
        os.environ["HOME"] = self.user

    def tearDown(self):
        os.environ["HOME"] = self.saved_home

    def status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["--home", self.home, "status"]), 0)
        return out.getvalue()

    def test_only_claude_code_without_leftovers(self):
        text = self.status()
        self.assertIn("工作中：Claude Code 2", text)
        self.assertNotIn("Codex", text)
        self.assertNotIn("dsh", text)

    def test_hints_for_legacy_codex_and_dsh_hooks(self):
        os.makedirs(os.path.join(self.user, ".codex"))
        hook = os.path.join(self.home, "bin", "ar_hook.py")
        with open(os.path.join(self.user, ".codex", "hooks.json"), "w") as f:
            json.dump({"hooks": {"Stop": [{"hooks": [{"command": "/usr/bin/python3 %s codex" % hook}]}]}}, f)
        dsh = os.path.join(self.home, "dsh-hooks.json")
        with open(dsh, "w") as f:
            f.write("{}")
        text = self.status()
        self.assertIn("~/.codex/hooks.json 里还有 agent-run 的旧 hook", text)
        self.assertIn("agent-run install-hooks 或 uninstall-hooks", text)
        self.assertIn("已不再支持 dsh", text)
        self.assertIn(dsh, text)

    def test_install_dsh_hooks_command_is_gone(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main(["--home", self.home, "install-dsh-hooks"])


if __name__ == "__main__":
    unittest.main()
