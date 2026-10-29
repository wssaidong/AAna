#!/usr/bin/env python3
"""回归测试: rec_optimizer --integrate 必须是幂等的

v2026-10-29 cron 复盘调参实测:

**缺陷**: `_integrate_to_generate_report()` 用正则
`# === REC_OPTIMIZER_TUNING_START ===\n.*?# === REC_OPTIMIZER_TUNING_END ===\n`
删旧块, 但**块前后的空行原样保留** → 每跑一次 `--integrate`,
generate_report.py 末尾就多留一行空行。

实测 2026-10-29 20:00: 该文件末尾累积了 **107 行空行**
(行 1626-1648 全是空), 而每次 commit 都带一条纯空行的无意义 diff。
历史 diff 佐证: 10-27 那轮 `git diff` 也是 "+1 空行"。

**修复**: 正则改成 `\n*START\n.*?END\n*` → 连同块前后的换行一起吃掉,
写回时用 `content.rstrip() + "\n\n\n" + block` 固定 2 空行分隔。

**验收标准 (skill 教训 i「两处代码都改对了 ≠ 链路通了」)**:
  必须真的连续跑两次 `--integrate`, 断言产出文件**内容相同**,
  而不是只断言单次跑完的快照 —— 单次跑完看不出累积。

注意: `generated_at` 每次都会变 (时间戳), 所以比较前要把它归一化。
"""
import os
import re
import sys
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import rec_optimizer


_TS_RE = re.compile(r'"generated_at": "[^"]*"')


def _normalize(text):
    """抹掉 generated_at 时间戳 (每次跑必然不同), 其余必须完全一致。"""
    return _TS_RE.sub('"generated_at": "<TS>"', text)


def _make_config():
    return rec_optimizer.TuningConfig(
        recommended_score_threshold=60,
        recommended_hold_days=1,
        weak_sectors=["造纸", "semi", "印制电路板"],
        score_band_stats={},
        hold_days_stats={},
        sector_stats={},
        total_records=367,
        overall_win_rate=49.9,
        generated_at="2026-10-29T20:00:00.000000",
    )


def _make_tmp_project(initial_content):
    """造一个临时项目目录 (tmp/scripts/generate_report.py), 返回 (tmpdir, report_path)。"""
    tmpdir = tempfile.mkdtemp()
    scripts = os.path.join(tmpdir, "scripts")
    os.makedirs(scripts, exist_ok=True)
    report_path = os.path.join(scripts, "generate_report.py")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(initial_content)
    return tmpdir, report_path


def _integrate_n_times(initial_content, times):
    """在临时项目里连跑 N 次 integrate, 返回每次跑完的文件内容列表。"""
    tmpdir, report_path = _make_tmp_project(initial_content)
    orig_dir = rec_optimizer.PROJECT_DIR
    rec_optimizer.PROJECT_DIR = Path(tmpdir)
    try:
        outputs = []
        for _ in range(times):
            rec_optimizer._integrate_to_generate_report(_make_config())
            with open(report_path, encoding="utf-8") as f:
                outputs.append(f.read())
    finally:
        rec_optimizer.PROJECT_DIR = orig_dir
        shutil.rmtree(tmpdir, ignore_errors=True)
    return outputs


def test_integrate_is_idempotent():
    """连跑两次 --integrate, 产出必须一致 (除 generated_at 时间戳)。"""
    first, second = _integrate_n_times(
        "def main():\n    print('hello')\n\n\nif __name__ == '__main__':\n    main()\n",
        2,
    )
    assert _normalize(first) == _normalize(second), (
        "--integrate 不幂等: 第二次跑完文件内容变了\n"
        f"--- 第一次尾部 ---\n{first[-400:]}\n"
        f"--- 第二次尾部 ---\n{second[-400:]}"
    )


def test_integrate_does_not_accumulate_blank_lines():
    """连跑 N 次, 块前空行数必须恒定 (不能每次 +1)。"""
    outputs = _integrate_n_times("def main():\n    pass\n", 4)
    counts = []
    for content in outputs:
        idx = content.find("# === REC_OPTIMIZER_TUNING_START ===")
        assert idx >= 0, "TUNING 块缺失"
        pre = content[:idx]
        counts.append(len(pre) - len(pre.rstrip("\n")))

    assert len(set(counts)) == 1, (
        f"空行数随 integrate 次数变化 (累积 bug 复发): {counts}"
    )
    assert counts[0] <= 3, f"块前空行过多: {counts[0]}"


def test_integrate_preserves_code_above_block():
    """integrate 不能吃掉块上方的业务代码, 且块不能重复。"""
    outputs = _integrate_n_times(
        "def main():\n    return 42\n", 2
    )
    content = outputs[-1]
    assert "def main():" in content, "业务代码被 integrate 吃掉"
    assert "return 42" in content, "业务代码被 integrate 吃掉"
    assert content.count("# === REC_OPTIMIZER_TUNING_START ===") == 1, \
        "integrate 后应恰好有一个 TUNING 块"
    assert content.count("# === REC_OPTIMIZER_TUNING_END ===") == 1, \
        "integrate 后应恰好有一个 TUNING 块"


def test_integrate_block_values_match_config():
    """写进文件的阈值/弱板块必须与 config 一致 (不能写错值)。"""
    content = _integrate_n_times("x = 1\n", 1)[0]
    assert '"score_threshold": 60' in content, "阈值写错"
    assert "造纸" in content and "semi" in content, "弱板块写错"
    assert '"total_records": 367' in content, "总记录数写错"


def test_integrate_block_is_valid_python():
    """integrate 后的文件必须仍能通过语法检查 (不能写坏 generate_report.py)。"""
    import ast
    content = _integrate_n_times(
        "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n", 2
    )[-1]
    try:
        ast.parse(content)
    except SyntaxError as e:
        raise AssertionError(f"integrate 后文件语法错误: {e}")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
