"""scripts/readme_screens.py 的示例数据要与只接 Claude Code 的固件一致（只接 Claude Code 方案 §8）。"""
import importlib.util
import os
import unittest

from agent_run.protocol import parse_device_line  # noqa: F401  确认 core 已在 sys.path 上

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "readme_screens.py")
_spec = importlib.util.spec_from_file_location("readme_screens", _PATH)
readme_screens = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(readme_screens)

# 固件跑速档位（ar_model.c）：只按 cc，0 睡觉、1 慢走、2-3 小跑、4-6 狂奔、>=7 冲刺
SPEED = {"sleep": range(0, 1), "walk": range(1, 2), "trot": range(2, 4), "run": range(4, 7), "dash": range(7, 100)}


class ReadmeScreensTest(unittest.TestCase):
    def test_screens_use_claude_only_and_match_speed_levels(self):
        screens = dict(readme_screens.SCREENS)
        for name, levels in SPEED.items():
            self.assertIn(screens[name].cc, levels, name)
        for name, snap in screens.items():
            self.assertEqual((snap.cx, snap.ds), (0, 0), name)
            self.assertEqual({tool for tool, _ in snap.waiting} - {"claude"}, set(), name)

    def test_sample_agent_frame_fills_home_tiles(self):
        # 首页三格显示 CC 的 A 帧：示例含一个 >=80% 的窗口（橙色）与后台运行
        line = readme_screens.agent_line(1794192000.0)
        fields = dict(item.split("=", 1) for item in line.split()[2:])
        self.assertEqual(fields["t"], "CC")
        self.assertGreaterEqual(int(fields["h"]), 80)
        self.assertNotIn(fields["w"], ("-", "x"))
        self.assertGreater(int(fields["bg"]), 0)


if __name__ == "__main__":
    unittest.main()
