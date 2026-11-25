"""订阅用量采集测试（专用页面方案 §3、§5.3）。

只接 Claude Code：用注入的凭据读取函数与请求函数，不访问钥匙串和网络。
"""
import json
import logging
import unittest

from agent_run.usage import (
    NO_LIMIT,
    ClaudePoller,
    EMPTY,
    UsageCollector,
    Window,
    claude_plan_label,
    parse_claude_credentials,
    parse_claude_usage,
)

NOW = 1794192000.0
TOKEN = "sk-ant-oat01-NEVER-LEAK-THIS"


class ClaudeParseTest(unittest.TestCase):
    def creds(self, token=TOKEN, expires_ms=(NOW + 3600) * 1000):
        return json.dumps({"claudeAiOauth": {"accessToken": token, "expiresAt": expires_ms}})

    def test_valid_token(self):
        self.assertEqual(parse_claude_credentials(self.creds(), NOW), (TOKEN, None))

    def test_expired_empty_or_broken_credentials(self):
        token, error = parse_claude_credentials(self.creds(expires_ms=(NOW - 1) * 1000), NOW)
        self.assertIsNone(token)
        self.assertIn("过期", error)
        for text in (self.creds(token="", expires_ms=0), "{}", "not json", ""):
            token, error = parse_claude_credentials(text, NOW)
            self.assertIsNone(token)
            self.assertIn("未登录", error)

    def test_usage_response(self):
        body = {
            "five_hour": {"utilization": 23.0, "resets_at": "2026-11-09T05:00:00.123456+00:00"},
            "seven_day": {"utilization": 41.5, "resets_at": "2026-11-12T00:00:00Z"},
            "seven_day_opus": None,
        }
        self.assertEqual(parse_claude_usage(body), (Window(23.0, 1794200400.123456), Window(41.5, 1794441600.0)))

    def test_usage_response_missing_or_empty_windows(self):
        body = {"five_hour": None, "seven_day": {"utilization": 3, "resets_at": None}}
        self.assertEqual(parse_claude_usage(body), (NO_LIMIT, Window(3.0, None)))
        self.assertEqual(parse_claude_usage({"seven_day": {"utilization": None}}), (NO_LIMIT, None))

    def test_usage_response_must_be_object(self):
        with self.assertRaises(ValueError):
            parse_claude_usage([])


class PlanLabelTest(unittest.TestCase):
    """订阅类型的显示名（专用页面方案 §9）。"""

    def creds(self, **oauth):
        oauth.setdefault("accessToken", TOKEN)
        return json.dumps({"claudeAiOauth": oauth})

    def test_claude_plans(self):
        cases = [
            ({"subscriptionType": "max", "rateLimitTier": "default_claude_max_5x"}, "Max 5x"),
            ({"subscriptionType": "max", "rateLimitTier": "default_claude_max_20x"}, "Max 20x"),
            ({"subscriptionType": "max"}, "Max"),
            ({"subscriptionType": "pro", "rateLimitTier": "default_claude_pro"}, "Pro"),
            ({"subscriptionType": "team"}, "Team"),
            ({"subscriptionType": "enterprise"}, "Enterprise"),
            ({"subscriptionType": "free"}, "Free"),
            ({"subscriptionType": "ultra_plus"}, "Ultra Plus"),     # 没见过的套餐按原文首字母大写
        ]
        for oauth, label in cases:
            self.assertEqual(claude_plan_label(self.creds(**oauth)), label, oauth)

    def test_claude_plan_needs_a_login(self):
        # 过期的令牌说明仍是这次登录的账号，套餐照常显示；令牌为空（已退出登录）时钥匙串里的套餐可能是旧的
        expired = self.creds(subscriptionType="pro", expiresAt=0)
        self.assertEqual(claude_plan_label(expired), "Pro")
        for text in (self.creds(subscriptionType="max", accessToken=""), self.creds(),
                     self.creds(subscriptionType=""), "{}", "not json", ""):
            self.assertIsNone(claude_plan_label(text), text)



class FakeClaude:
    """可编排的凭据与请求结果；记录发出的请求次数与使用的令牌。"""

    def __init__(self):
        self.token = TOKEN
        self.responses = []
        self.requests = []

    def read_credentials(self):
        return json.dumps({"claudeAiOauth": {
            "accessToken": self.token, "expiresAt": (NOW + 86400) * 1000,
            "subscriptionType": "max", "rateLimitTier": "default_claude_max_5x",
        }})

    def fetch(self, token):
        self.requests.append(token)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


OK_BODY = json.dumps({"five_hour": {"utilization": 23.0, "resets_at": None},
                      "seven_day": {"utilization": 41.0, "resets_at": None}}).encode()


class ClaudePollerTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeClaude()
        self.poller = ClaudePoller(read_credentials=self.fake.read_credentials, fetch=self.fake.fetch)

    def test_success_then_every_five_minutes(self):
        self.fake.responses = [(200, OK_BODY)]
        self.assertTrue(self.poller.due(NOW))
        self.poller.poll(NOW)
        usage = self.poller.result(NOW)
        self.assertEqual((usage.five_hour, usage.seven_day), (Window(23.0, None), Window(41.0, None)))
        self.assertEqual(usage.updated, NOW)
        self.assertEqual(usage.plan, "Max 5x")
        self.assertFalse(self.poller.due(NOW + 299))
        self.assertTrue(self.poller.due(NOW + 300))

    def test_refresh_after_stop_keeps_sixty_second_gap(self):
        self.fake.responses = [(200, OK_BODY)]
        self.poller.poll(NOW)
        self.poller.request_refresh(NOW + 10)
        self.assertFalse(self.poller.due(NOW + 59))
        self.assertTrue(self.poller.due(NOW + 60))

    def test_expired_token_sends_no_request(self):
        self.poller = ClaudePoller(
            read_credentials=lambda: json.dumps({"claudeAiOauth": {"accessToken": TOKEN, "expiresAt": 0}}),
            fetch=self.fake.fetch)
        self.poller.poll(NOW)
        self.assertEqual(self.fake.requests, [])
        self.assertIn("过期", self.poller.result(NOW).error)
        self.assertTrue(self.poller.due(NOW + 300))

    def test_plan_is_read_even_without_a_request(self):
        # 令牌过期时不发请求，但套餐照常从凭据里读出
        creds = {"accessToken": TOKEN, "expiresAt": 0, "subscriptionType": "pro"}
        self.poller = ClaudePoller(read_credentials=lambda: json.dumps({"claudeAiOauth": creds}),
                                   fetch=self.fake.fetch)
        self.poller.poll(NOW)
        self.assertEqual(self.poller.result(NOW).plan, "Pro")
        self.assertEqual(self.fake.requests, [])

    def test_unauthorized_waits_for_a_new_token(self):
        self.fake.responses = [(401, b""), (200, OK_BODY)]
        self.poller.poll(NOW)
        self.assertIn("401", self.poller.result(NOW).error)
        self.poller.poll(NOW + 300)              # 令牌没变：不再请求
        self.assertEqual(len(self.fake.requests), 1)
        self.fake.token = TOKEN + "-new"
        self.poller.poll(NOW + 600)              # 令牌变了：重新请求
        self.assertEqual(len(self.fake.requests), 2)
        self.assertIsNone(self.poller.result(NOW + 600).error)

    def test_rate_limit_and_network_errors_back_off(self):
        self.fake.responses = [(429, b""), OSError("boom"), OSError("boom"), OSError("boom"), (200, OK_BODY)]
        t = NOW
        gaps = []
        for _ in range(4):
            self.poller.poll(t)
            gap = 60
            while not self.poller.due(t + gap):
                gap += 60
            gaps.append(gap)
            t += gap
        self.assertEqual(gaps, [300, 600, 1200, 1200])
        # 退避期间 Stop 不提前请求
        self.poller.request_refresh(t - 1100)
        self.assertFalse(self.poller.due(t - 1100))
        self.poller.poll(t)
        self.assertTrue(self.poller.due(t + 300))
        self.assertIsNone(self.poller.result(t).error)

    def test_failure_keeps_recent_data_then_expires_it(self):
        self.fake.responses = [(200, OK_BODY), (429, b"")]
        self.poller.poll(NOW)
        self.poller.poll(NOW + 300)
        self.assertEqual(self.poller.result(NOW + 300).seven_day, Window(41.0, None))
        self.assertIsNone(self.poller.result(NOW + 1801).seven_day)

    def test_bad_body_is_reported(self):
        self.fake.responses = [(200, b"<html>")]
        self.poller.poll(NOW)
        self.assertIn("解析", self.poller.result(NOW).error)

    def test_token_never_reaches_results_or_logs(self):
        self.fake.responses = [OSError("connect to %s failed" % TOKEN), (401, TOKEN.encode()), (200, OK_BODY)]
        with self.assertLogs("agent-run", level="DEBUG") as logs:
            logging.getLogger("agent-run").debug("start")
            for i in range(3):
                self.poller.poll(NOW + i * 1200)
                if i == 1:
                    self.fake.token = TOKEN + "2"
                text = json.dumps(self.poller.result(NOW + i * 1200))
                self.assertNotIn(TOKEN, text)
        self.assertNotIn(TOKEN, "\n".join(logs.output))


class FakePoller:
    """记录 Stop 刷新请求的 Claude 轮询器替身。"""

    def __init__(self):
        self.refreshes = []
        self.polls = []

    def due(self, now):
        return True

    def poll(self, now):
        self.polls.append(now)

    def request_refresh(self, now):
        self.refreshes.append(now)

    def result(self, now):
        return None


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.claude = FakePoller()
        self.collector = UsageCollector(claude=self.claude, threaded=False)

    def test_claude_stop_requests_refresh_and_unthreaded_step_polls(self):
        self.collector.on_stop("claude", NOW)
        self.collector.step(NOW)
        self.assertEqual(self.claude.refreshes, [NOW])
        self.assertEqual(self.claude.polls, [NOW])

    def test_other_tools_have_no_data(self):
        # 只接 Claude Code：Codex 用量不再读取
        self.collector.on_stop("codex", NOW)
        self.collector.step(NOW)
        for tool in ("codex", "dsh"):
            self.assertEqual(self.collector.get(tool), EMPTY)


if __name__ == "__main__":
    unittest.main()
