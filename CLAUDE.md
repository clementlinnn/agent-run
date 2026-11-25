# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 回覆語言

一律以繁體中文回答使用者。這條規則只管對話中的回覆；倉庫內的文件、註解、介面文字與 commit 訊息仍依下方 Conventions 使用簡體中文。

## What this is

Agent Run! aggregates locally running Claude Code sessions into a status display: a pet that runs faster the more sessions are working and waves and beeps when a session waits for you, with the Claude Code 5-hour and weekly usage on the home screen. Since 0.7 only Claude Code is collected; Codex and dsh support was removed, but the protocol still carries `cx=0 ds=0` so old and new firmware/collector versions interoperate (see `docs/specs/2026-11-25-agent-run-claude-only-design.md`). The current display is the FoloToy AI Passport (ESP32-C3, 240×320) over USB serial or BLE. macOS only.

Three independent components talk only through the documented protocol in `docs/protocol.md`:

- `core/`: Python collector (hook entry, session state machine, daemon, CLI). **Standard library only, must run on the system `/usr/bin/python3` (3.9)**, the interpreter that hooks and launchd use. No third-party packages, no 3.10+ syntax.
- `transports/macos-ble/`: Swift BLE bridge `AgentRunBridge.app` (CoreBluetooth). Python has no BLE, so the daemon hands lines to this bridge over a socket.
- `displays/ai-passport/`: ESP-IDF 5.5.3 firmware.

## Commands

```bash
scripts/check.sh              # all tests: Python (core), Swift (bridge), firmware host tests (C, compiled with cc)
scripts/check.sh --firmware   # also idf.py build + merged image (first run: . ~/esp/esp-idf-v5.5.3/export.sh)

# Single Python test (run from repo root; -t core sets the top-level dir)
/usr/bin/python3 -m unittest discover -s core/tests -t core -p test_state.py
/usr/bin/python3 -m unittest tests.test_state.AggregatorTest      # one class or method, run from inside core/

# Swift
(cd transports/macos-ble && swift test)
transports/macos-ble/build.sh   # build + ad-hoc sign + install to ~/Applications/AgentRunBridge.app

# One firmware host test (pattern copied from check.sh)
cc -std=c11 -Wall -Wextra -Werror -Idisplays/ai-passport/main \
   displays/ai-passport/tests/test_ar_model.c displays/ai-passport/main/agent_run/ar_model.c -o /tmp/model && /tmp/model

# Run the CLI from the repo
core/bin/agent-run status --events
core/bin/agent-run install-service   # redeploys core to ~/.agent-run and restarts the launchd service
```

The daemon holds the serial port. Before flashing firmware or taking `agent-run screenshot`, stop it with `launchctl bootout gui/$(id -u)/local.agent-run`, and bring it back with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.agent-run.plist`. For routine updates, flash with `idf.py -C displays/ai-passport -p /dev/cu.usbmodem101 flash`. Writing the merged image at `0x0` wipes NVS (settings and BLE bonding).

## Architecture

Data flow: agent hook → `core/bin/ar_hook.py` → Unix datagram `$AGENT_RUN_HOME/run/ar.sock` → daemon → USB serial (`serial_link.py`) or `ble.sock` → Swift bridge → BLE → device. The daemon also writes `~/.agent-run/run/status.json` for local displays.

- **`ar_hook.py` is deliberately standalone.** It does not import `agent_run`, always exits 0 with no stdout/stderr, and forwards only whitelisted fields (session id, event name, tool name). Prompts, paths and tool args are never forwarded. Keep it fast and silent: it runs inside every agent hook.
- **`state.py` is pure logic.** No I/O, and the clock and local-date functions are injected so timeouts and the day rollover can be tested with a fake clock. Per-session states: idle / working / waiting / background, with timeout reaping. The event→state mapping is in `docs/specs/2026-11-08-agent-run-design.md` §5.
- **`daemon.py`** drains the socket, keeps the state, picks a link (USB preferred, falls back to BLE via `ble_link.py`, which shares `SerialLink`'s interface), sends AR1 `S` status frames (state change plus heartbeat) and `A` per-tool frames (on change or HELLO), and persists "done today". Its dependencies (clock, link factory, port finder, usage) are injected for tests.
- **`usage.py`**: Claude Code subscription usage. It reads the CLI token from the keychain item `Claude Code-credentials` and calls a non-public usage endpoint.
- **`install.py`**: appends its own entries to `~/.claude/settings.json` and removes entries a pre-0.7 install left in `~/.codex/hooks.json` (backups go to `~/.agent-run/backup/`), and writes the launchd plists. Never modify the user's existing hooks.
- **Firmware** (`displays/ai-passport/main/`): `main.c` runs the app task loop. All display, timing, backlight, DND, menu and power-detection *rules* live in `ar_model.c` (pure C, host-testable). `ar_proto.c` parses AR1, `ar_raster.c`/`ar_sprite.c` draw the pet and the 5×7 digits, and `ar_ui.c` is the LVGL glue. To make logic testable on the host, put it in `ar_model`/`ar_proto`/etc., not in `main.c` or `ar_ui.c`. `components/bsp/` and a few root files come from FoloToy/ai-passport (MIT); update them by diffing against upstream.
- Firmware version is `AR_FW_VERSION` in `main/agent_run/ar_link.h` (reported in `AR1 HELLO`).

## Protocol and privacy invariants

- `docs/protocol.md` is the contract between collector and displays. Any frame or field change updates it and must stay compatible: displays ignore unknown keys and non-`AR1 ` lines, and drop the whole frame on missing, out-of-range or overlong fields. Lines are at most 160 bytes.
- Only counts, tool codes, reason codes, usage percentages, plan name and local minute-of-day leave the host. No account names, project names, paths, prompts or session content.

## Firmware constraints

- Memory is tight. The LVGL pool is 32 KB with only about 3.3 KB free, and the screenshot strip buffer must fit in the free heap. Check the resource numbers in `displays/ai-passport/README.md` before adding UI elements.
- All UI Chinese text lives in `main/agent_run/ar_text.h`. After changing it, regenerate the font subset with `displays/ai-passport/tools/gen_agent_run_font.sh`. `tests/test_ar_font_coverage.py` fails if a glyph is missing.
- README screenshots are regenerated from the real device via `scripts/readme_screens.py` (FAP_SCREENSHOT_V1 over USB).

## Conventions

- Docs, code comments, UI text and commit messages are in Simplified Chinese. Commits follow Conventional Commits with scopes like `feat(core):`, `fix(firmware):`, `docs:`. Features are developed on `feat/*` / `fix/*` branches and merged into `main` with merge commits.
- Each feature has a design doc in `docs/specs/YYYY-MM-DD-*-design.md`, and code comments cite its sections (e.g. "设计方案 §5.2"). Real-device measurements and acceptance results are recorded back into these specs, and user-visible behavior and limitations are reflected in `README.md` (features, device controls, known limitations).
