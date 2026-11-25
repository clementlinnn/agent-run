# 只接 Claude Code 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 采集端只接 Claude Code,首页底部三格改为 Claude 的 5 小时用量、每周用量、后台运行,去掉 Codex 专用页面。

**Architecture:** 协议不变,采集端照旧发 `cx=0 ds=0`;采集端删掉 Codex、dsh 的采集与安装;固件只按 `cc` 计算跑速,页面只剩首页与 Claude 页,首页三格读 Claude 的 A 帧。

**Tech Stack:** Python 3.9 标准库(`/usr/bin/python3`)、C11 + LVGL(ESP-IDF 5.5.3)、宿主测试用 `cc`。

**Spec:** `docs/specs/2026-11-25-agent-run-claude-only-design.md`

## Global Constraints

- core 只用标准库,语法兼容 Python 3.9。
- 协议格式不变:状态帧仍带 `cx`、`ds`(恒为 0),固件仍能解析 `cx`、`ds`、`CX`、`DS`、`t=CX`。
- 用量 ≥ 80% 用橙色(沿用 `ar_usage_alert()`);暂无数据与无此限额都显示暗色 `--`。
- 固件版本 `0.7.0`。
- 不重新生成字库:新文案只能用 `ar_text.h` 已有的汉字。
- 文档、注释、提交信息用简体中文。

## Review Focus

1. 旧版装进 `~/.codex/hooks.json` 的条目仍会调用 `ar_hook.py codex`:必须静默丢弃,不能计入任何计数。→ Task 1 测试。
2. `install-hooks` 清理 Codex 条目时不能动使用者自己的其他 Codex hook,文件不存在时不能新建。→ Task 2 测试。
3. 首页三格在还没收到 A 帧(旧采集端)时显示 `--`/0,而不是上一帧残留或垃圾值。→ Task 4 由 `has_agent` 判断。
4. `h=100` 的 `100%` 在 56 px 格子里放不下:改用 2 倍字号。→ Task 4。
5. 旧采集端送来的 `CX`/`DS` 等待项照常进入等你处理画面。→ Task 3 保留现有等待测试不改。

---

### Task 1: 采集端只处理 Claude Code 事件

**Files:**
- Modify: `core/bin/ar_hook.py`(`TOOLS = ("claude",)`)
- Modify: `core/agent_run/state.py`(`HOOK_TOOLS = ("claude",)`,删掉 `set_dsh_working`、`_dsh_working`、`_dsh_hooks_seen`;`snapshot()` 的 `cx`、`ds` 恒为 0)
- Modify: `core/agent_run/daemon.py`(删 dsh 扫描与 `dsh_root` 参数;`AGENT_TOOLS = ("claude",)`;`DEMO_SCREENS`、`DEMO_AGENTS` 只用 Claude,等你处理一屏为 `[("claude","A"),("claude","Q")]`)
- Modify: `core/agent_run/usage.py`(删 Codex 读取:`read_codex_usage`、`classify_codex_limits`、`codex_plan_label`、`CODEX_*`、`UsageCollector` 的 Codex 分支与 `codex_root` 参数)
- Modify: `core/agent_run/cli.py`(`cmd_run` 不再传 `dsh_root`)
- Delete: `core/agent_run/dsh.py`、`core/tests/test_dsh.py`
- Test: `core/tests/test_hook.py`、`test_state.py`、`test_daemon.py`、`test_usage.py`

**Interfaces:**
- Produces: `Snapshot` 字段不变(`cc cx ds done wn waiting`);`Aggregator.tool_counts()` 只含 `"claude"`;`UsageCollector(claude=None, clock=time.time, threaded=True)`;`Daemon(...)` 无 `dsh_root`。

- [ ] **Step 1: 改测试**
  - `test_hook`:`main(["ar_hook.py", "codex"])` 与 `"dsh"` 不发送数据报。
  - `test_state`:`handle({"tool":"codex",...})` 返回 False 且 `session_count()==0`;Claude 会话工作中时 `snapshot().cx == 0 and .ds == 0`;`tool_counts()` 的键只有 `claude`。删除 Codex/dsh 专属用例。
  - `test_daemon`:A 帧只发 `t=CC`;`status.json` 的 `agents` 只有 `claude`、`cx`/`ds` 为 0;演示帧不含 `CX`。
  - `test_usage`:删除 Codex 用例,`UsageCollector().get("codex") == EMPTY`。
- [ ] **Step 2: 运行确认失败** `/usr/bin/python3 -m unittest discover -s core/tests -t core`
- [ ] **Step 3: 实现上述删改**
- [ ] **Step 4: 运行确认通过**(同上命令,`OK`)
- [ ] **Step 5: 提交** `feat(core): 只采集 Claude Code,不再采集 Codex 与 dsh`

### Task 2: 安装与 status 只管 Claude,清理旧残留

**Files:**
- Modify: `core/agent_run/install.py`
- Modify: `core/agent_run/cli.py`
- Test: `core/tests/test_install.py`、`core/tests/test_cli.py`

**Interfaces:**
- Produces:
  - `install_hooks(claude_path, codex_path, python, hook_path, backup_dir) -> str`:只给 Claude 追加;`codex_path` 存在时删除其中指向 `hook_path` 的条目(`_remove_hooks`),不存在时不创建。两者修改前都备份。
  - `uninstall_hooks(...)` 不变。
  - `has_our_hooks(path, hook_path) -> bool`:配置文件里是否还有指向本 hook 的条目;文件不存在或损坏时 False。
  - 删除 `CODEX_EVENTS`、`DSH_EVENTS`、`dsh_hooks_config`、`codex_untrusted_events`、`_snake_case` 及仅为其服务的代码;删除 `cmd_install_dsh_hooks` 与子命令注册。
- `cmd_status`:工作中一行改为 `工作中：Claude Code %d`;`~/.codex/hooks.json` 有残留时打印 `注意：~/.codex/hooks.json 里还有 agent-run 的旧 hook，执行 agent-run install-hooks 或 uninstall-hooks 可以清掉。`;`<home>/dsh-hooks.json` 存在时打印 `注意：已不再支持 dsh。请从 dsh profile 的 cordis.patch.yml 里拿掉 dsh-hooks-claude-code 插件，再删除 <路径>。`
- `cmd_install_hooks` 输出:`已为 Claude Code 安装 hook，原配置备份在 %s。`

- [ ] **Step 1: 写测试**:`install_hooks` 后 Codex 文件里只剩使用者自己的条目;Codex 文件不存在时仍不存在;`has_our_hooks` 真假两例;`status` 输出含上述两条提示(用临时 home 与 `HOME`)且不含 `Codex`。
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 运行确认通过**
- [ ] **Step 5: 提交** `feat(core): install-hooks 只装 Claude 并清掉 Codex 旧条目,status 提示残留`

### Task 3: 固件规则只按 Claude 计算,页面只剩两页

**Files:**
- Modify: `displays/ai-passport/main/agent_run/ar_model.c`、`ar_model.h`
- Test: `displays/ai-passport/tests/test_ar_model.c`

**Interfaces:**
- Produces: `ar_page_t` 为 `AR_PAGE_HOME, AR_PAGE_CC, AR_PAGE_COUNT`;`ar_model_working_total(s)` 返回 `s->cc`。

- [ ] **Step 1: 改测试**:跑速档位表改成只看 `cc`(`{0,5,5}`→睡觉、`{1,9,9}`→慢走、`{2,0,0}`→小跑、`{4,0,0}`→狂奔、`{7,0,0}`→冲刺);`working_total(99,99,99)==99`;页面切换 `HOME±1→CC`、`CC±1→HOME`、`CC+2→CC`、`200+1→CC`;`ar_page_shown(AR_PAGE_CC, AR_SCREEN_WAITING)==AR_PAGE_HOME`。等待相关测试不动。
- [ ] **Step 2: 运行确认失败**(check.sh 的 model 编译命令)
- [ ] **Step 3: 实现**
- [ ] **Step 4: `scripts/check.sh` 通过**
- [ ] **Step 5: 提交** `feat(firmware): 跑速只按 Claude Code 计算,去掉 Codex 页面`

### Task 4: 首页三格改为用量与后台运行

**Files:**
- Modify: `displays/ai-passport/main/main.c`(`view.page` 之外始终用 `AR_TOOL_CC` 填 `view.has_agent`、`view.agent`;`agent_flash` 照旧)
- Modify: `displays/ai-passport/main/agent_run/ar_ui.c`
- Modify: `displays/ai-passport/main/agent_run/ar_text.h`(新增 `AR_TXT_TILE_FIVE_HOUR "5 小时"`、`AR_TXT_TILE_WEEK "每周"`)
- Modify: `displays/ai-passport/main/agent_run/ar_link.h`(`AR_FW_VERSION "0.7.0"`)

- `ar_ui.c`:新增 `static void draw_usage_tile(int index, uint8_t percent)`:已知时 `"%u%%"`,宽度超过 `TILE_CANVAS_W` 时改 2 倍字号,颜色按 `ar_usage_alert`;未知 / 无此限额画暗色 `--`。首页三格为 `draw_usage_tile(0, h)`、`draw_usage_tile(1, w)`、`draw_agent_tile(2, bg, C_TEXT)`,没收到 A 帧时 h/w 用 `AR_USAGE_UNKNOWN`、bg 用 0;首页也显示中文标签(`5 小时`、`每周`、`后台运行`),专用页面切回原标签。删掉 `draw_tile()` 与 `CC/CODEX/DSH` 名称;`update_agent_page` 不再判断 CX。
- [ ] **Step 1: `scripts/check.sh` 通过,`test_ar_font_coverage.py` 覆盖新文案**
- [ ] **Step 2: 若有 ESP-IDF,`scripts/check.sh --firmware` 构建通过;没有则在交付说明里写明未构建**
- [ ] **Step 3: 提交** `feat(firmware): 首页三格显示 Claude Code 用量与后台运行,固件 0.7.0`

### Task 5: 文档

**Files:** `docs/protocol.md`、`README.md`、`CLAUDE.md`、`docs/specs/2026-11-25-agent-run-claude-only-design.md`

- protocol:§1、§2.1 注明 `cx`、`ds` 由本采集端恒发 0,展示端可忽略;A 帧只发 `t=CC`;§5 `agents` 只含 `claude`。
- README:简介、功能(首页三格、页面只剩两页)、支持情况只留 Claude Code、工作原理图、快速开始删 Codex 信任与 dsh 两步、命令参考删 `install-dsh-hooks`、设备操作的上下键、故障排查与已知限制删 Codex/dsh 项、新增“从旧版升级”说明(执行 `install-hooks` 清掉 Codex 旧条目)。截图注明待重拍。
- CLAUDE.md:同步“只接 Claude Code”。
- spec:状态改为“已确认,实现中”,记录未做的真机验收。
- [ ] **Step 1: 改文档** **Step 2: 提交** `docs: 协议、README 与 CLAUDE.md 改为只接 Claude Code`
