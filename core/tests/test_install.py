"""hook 安装与卸载测试（设计方案 §5.2「安装与卸载」）。"""
import json
import os
import plistlib
import tempfile
import unittest

from agent_run.install import (
    CLAUDE_EVENTS,
    has_our_hooks,
    install_hooks,
    launchd_plist,
    uninstall_hooks,
)

HOOK = "/Users/test/.agent-run/bin/ar_hook.py"


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


def read_json(path):
    with open(path) as f:
        return json.load(f)


class InstallHooksTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.claude = os.path.join(self.dir, "settings.json")
        self.codex = os.path.join(self.dir, "hooks.json")
        self.backup = os.path.join(self.dir, "backup")
        self.other = {"type": "command", "command": "/usr/local/bin/other-tool"}
        write_json(self.claude, {
            "model": "opus",
            "hooks": {"Stop": [{"hooks": [self.other]}]},
        })
        # 旧版 agent-run 给 Codex 装过的条目，与使用者自己的条目放在一起
        self.legacy = {"type": "command", "command": "/usr/bin/python3 %s codex" % HOOK, "async": True, "timeout": 2}
        write_json(self.codex, {"hooks": {
            "Stop": [{"hooks": [self.other]}, {"hooks": [dict(self.legacy)]}],
            "SessionStart": [{"hooks": [dict(self.legacy)]}],
        }})

    def install(self):
        return install_hooks(self.claude, self.codex, "/usr/bin/python3", HOOK, self.backup)

    def test_appends_entries_for_every_event_and_keeps_others(self):
        self.install()
        claude = read_json(self.claude)
        self.assertEqual(claude["model"], "opus")
        self.assertEqual(set(claude["hooks"]), set(CLAUDE_EVENTS))
        self.assertIn({"hooks": [self.other]}, claude["hooks"]["Stop"])
        ours = [h for g in claude["hooks"]["Stop"] for h in g["hooks"] if HOOK in h["command"]]
        self.assertEqual(ours, [{"type": "command", "command": "/usr/bin/python3 %s claude" % HOOK, "async": True}])

    def test_install_removes_legacy_codex_entries_and_keeps_others(self):
        # 只接 Claude Code：install-hooks 顺手清掉旧版装进 Codex 的条目，使用者自己的条目不动
        self.install()
        self.assertEqual(read_json(self.codex), {"hooks": {"Stop": [{"hooks": [self.other]}]}})
        self.assertFalse(has_our_hooks(self.codex, HOOK))

    def test_install_is_idempotent(self):
        self.install()
        first = read_json(self.claude)
        self.install()
        self.assertEqual(read_json(self.claude), first)

    def test_backs_up_existing_files_before_writing(self):
        self.install()
        backups = []
        for root, _, files in os.walk(self.backup):
            backups.extend(files)
        self.assertEqual(sorted(backups), ["hooks.json", "settings.json"])

    def test_missing_files_are_created(self):
        os.remove(self.claude)
        os.remove(self.codex)
        self.install()
        self.assertEqual(set(read_json(self.claude)["hooks"]), set(CLAUDE_EVENTS))
        self.assertFalse(os.path.exists(self.codex))   # 不再为 Codex 新建配置

    def test_uninstall_removes_only_our_entries(self):
        before_claude = read_json(self.claude)
        self.install()
        uninstall_hooks(self.claude, self.codex, HOOK, self.backup)
        self.assertEqual(read_json(self.claude), before_claude)
        self.assertEqual(read_json(self.codex), {"hooks": {"Stop": [{"hooks": [self.other]}]}})

    def test_uninstall_also_clears_legacy_codex_entries(self):
        # 没执行过新版 install-hooks 的旧安装，uninstall-hooks 也能把 Codex 里的条目清干净
        uninstall_hooks(self.claude, self.codex, HOOK, self.backup)
        self.assertEqual(read_json(self.codex), {"hooks": {"Stop": [{"hooks": [self.other]}]}})


class HasOurHooksTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "hooks.json")

    def test_detects_entries_pointing_at_our_hook(self):
        write_json(self.path, {"hooks": {"Stop": [{"hooks": [{"command": "/usr/bin/python3 %s codex" % HOOK}]}]}})
        self.assertTrue(has_our_hooks(self.path, HOOK))

    def test_other_entries_missing_or_broken_files_are_false(self):
        write_json(self.path, {"hooks": {"Stop": [{"hooks": [{"command": "/usr/local/bin/other"}]}]}})
        self.assertFalse(has_our_hooks(self.path, HOOK))
        self.assertFalse(has_our_hooks(os.path.join(self.dir, "none.json"), HOOK))
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertFalse(has_our_hooks(self.path, HOOK))
        write_json(self.path, ["not", "a", "dict"])
        self.assertFalse(has_our_hooks(self.path, HOOK))


class DeployTest(unittest.TestCase):
    def test_redeploy_from_deployed_copy_keeps_files(self):
        # 已部署的 agent-run 再执行部署时，来源就是目标本身：不能先删后拷
        from agent_run.install import deploy
        host_dir = os.path.join(os.path.dirname(__file__), "..")
        home = tempfile.mkdtemp()
        deploy(host_dir, home)
        deployed_host = os.path.join(home, "lib")
        hook, script = deploy(deployed_host, home)
        self.assertTrue(os.path.isfile(os.path.join(home, "lib", "agent_run", "state.py")))
        self.assertTrue(os.path.isfile(hook) and os.path.isfile(script))


class BridgePlistTest(unittest.TestCase):
    def test_bridge_plist_runs_app_executable(self):
        from agent_run.install import BRIDGE_LABEL, bridge_plist
        data = plistlib.loads(bridge_plist("/A/AgentRunBridge.app", "/h/.agent-run"))
        self.assertEqual(data["Label"], BRIDGE_LABEL)
        self.assertEqual(data["ProgramArguments"], ["/A/AgentRunBridge.app/Contents/MacOS/AgentRunBridge"])
        self.assertEqual(data["EnvironmentVariables"], {"AGENT_RUN_HOME": "/h/.agent-run"})
        self.assertTrue(data["KeepAlive"])


class LaunchdTest(unittest.TestCase):
    def test_plist_runs_daemon_and_keeps_alive(self):
        data = plistlib.loads(launchd_plist("/usr/bin/python3", "/h/.agent-run/bin/agent-run", "/h/.agent-run"))
        self.assertEqual(data["Label"], "local.agent-run")
        self.assertEqual(data["ProgramArguments"], ["/usr/bin/python3", "/h/.agent-run/bin/agent-run", "run"])
        self.assertTrue(data["RunAtLoad"])
        self.assertTrue(data["KeepAlive"])
        self.assertEqual(data["StandardErrorPath"], "/h/.agent-run/log/agent-run.log")


if __name__ == "__main__":
    unittest.main()
