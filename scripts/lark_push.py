#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lark_push.py — 飞书推送统一封装 (2026-10-27 修)

P0 修复背景:
  launchd 跑的 AAna 脚本 (daily_v24_recommend / daily_v24_sell / run_afterhours)
  从 2026-09-01 起连续 177 次推送失败, 报错 `config / not_configured`。
  根因: lark-cli 解析配置时需要 `HERMES_HOME` 才能定位 workspace
  (~/.lark-cli/hermes/config.json)。Hermes cron 环境下该变量由 Hermes 注入,
  所以 cron 内跑的都正常; 但 launchd 只设了 PATH, 没设 HERMES_HOME,
  lark-cli 找不到 workspace → "not_configured" → 所有 launchd 推送静默失败。

  已实测验证 (env -i 最小环境):
    HOME=/Users/cai                             → not_configured ❌
    HOME=/Users/cai HERMES_HOME=/Users/cai/.hermes → ok ✅ (workspace=hermes)

用法:
    from lark_push import push_markdown
    push_markdown(md, user_id="ou_xxx")          # P2P (默认)
    push_markdown(md, chat_id="oc_xxx")          # 群聊

注意:
  - 用 `--as bot` 显式指定身份: `--user-id` 只在 user 身份下接受, bot 身份必须传 `--chat-id`。
    这里默认走 user_id 时自动改用 `--as user`。
  - 只补 HERMES_HOME, 不覆盖调用方已有环境。
"""
import os
import subprocess
from typing import Optional

# lark-cli 解析 workspace 配置所需 (指向 ~/.lark-cli/<workspace>/config.json)
HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


def push_markdown(markdown: str, user_id: Optional[str] = None,
                  chat_id: Optional[str] = None,
                  timeout: int = 30, dry_run: bool = False):
    """
    推送 markdown 到飞书。返回 (ok: bool, detail: str)。

    user_id / chat_id 二选一; 都不传则报错。
    """
    if not user_id and not chat_id:
        return False, "必须指定 user_id 或 chat_id"

    env = dict(os.environ)
    env["HERMES_HOME"] = HERMES_HOME

    cmd = ["lark-cli", "im", "+messages-send"]
    # strict mode = "bot" (实测 ~/.lark-cli/hermes/config.json), 只允许 bot 身份
    if chat_id:
        cmd += ["--chat-id", chat_id]
    else:
        cmd += ["--user-id", user_id]
    cmd += ["--as", "bot", "--markdown", markdown]
    if dry_run:
        cmd.append("--dry-run")

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except Exception as e:
        return False, f"异常: {type(e).__name__}: {e}"

    if r.returncode == 0:
        return True, (r.stdout or "")[:300]
    return False, (r.stderr or r.stdout or "")[:300]


if __name__ == "__main__":
    import sys
    md = sys.stdin.read()
    ok, detail = push_markdown(md, user_id="ou_5d0124d26ed21365f74764fcb9fa01b7", dry_run=True)
    print("ok:", ok)
    print(detail)
