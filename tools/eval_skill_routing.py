"""Which skill does `auto` choose? A small, deterministic routing eval.

The panel's default is 自动 (`skill='auto'`): the turn asks the framework's `Skills.route` to pick
an expert mode from the sentence and says which one it chose. That router is keyword scoring, not a
model, so its quality is a MEASURING question with a reproducible answer: this script routes the
same utterances every run and prints how many it got right.

It is not a pytest gate (the table is a reading a person refines; `tests/unit/ai/test_skill_routing.py`
pins the same table as a regression), and it needs no provider or key:

    python tools/eval_skill_routing.py
    python tools/eval_skill_routing.py --json docs/testing/skill-routing.json

A row may name more than one acceptable skill: "帮我做定性编码，两个人编码比较 kappa" is genuinely
the qualitative and the quantitative mode at once, and scoring one of them wrong would measure the
table, not the router.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'backend'))

#: One line per task: what a user types, and the skill(s) that are a correct answer. The utterances
#: are the ones the panel's starter chips and the docs actually use — a router that only understands
#: `catbus` because that word is also its id is exactly the failure this table found.
TASKS = (
    {'id': 'project-start', 'prompt': '怎么用这个项目开始？', 'skills': ('project',)},
    {'id': 'crawl-zhihu', 'prompt': '帮我采集知乎的帖子', 'skills': ('crawl',)},
    {'id': 'catbus-weibo', 'prompt': '用 catbus 装好之后抓一次微博', 'skills': ('catbus',)},
    {'id': 'diagnose-failure', 'prompt': '这次运行为什么失败了？', 'skills': ('diagnose',)},
    {'id': 'monitor-notify', 'prompt': '跑完通知我，或者出错告诉我', 'skills': ('monitor',)},
    {'id': 'python-script', 'prompt': '帮我写一个 python 脚本清洗正文', 'skills': ('python',)},
    {'id': 'conductor-whole-flow', 'prompt': '把采集、分析、出图串起来跑一遍', 'skills': ('conductor',)},
    {'id': 'models-pick', 'prompt': '该用哪个小模型？', 'skills': ('models',)},
    {'id': 'models-distill', 'prompt': '怎么把模型蒸馏成更小的', 'skills': ('model_tuning',)},
    {
        'id': 'coding-both-senses',
        'prompt': '帮我做定性编码，两个人编码比较 kappa',
        'skills': ('qualitative_coding', 'quantitative_coding'),
    },
    {'id': 'coding-kappa', 'prompt': '做双人编码并报告 kappa', 'skills': ('quantitative_coding',)},
    {'id': 'analysis-topic', 'prompt': '对正文做主题分析和情感分析', 'skills': ('analysis',)},
    {'id': 'workflow-build', 'prompt': '帮我搭一个采集到图表的工作流', 'skills': ('workflow',)},
    {'id': 'charts-topic-map', 'prompt': '画一张主题距离图', 'skills': ('charts',)},
    {'id': 'report-write', 'prompt': '把分析结果写成报告', 'skills': ('report',)},
    {'id': 'research-news', 'prompt': '查一下这个平台最近的公开规则', 'skills': ('research',)},
    {'id': 'skill-author', 'prompt': '帮我创建一个技能', 'skills': ('skill_author',)},
    {'id': 'developer-module', 'prompt': '运行恢复的入口在哪个模块？', 'skills': ('developer',)},
)


def _workspace():
    """The real host + workspace, on an isolated data root: only the router is under test."""
    from agent_workspace import AgentWorkspace
    from ai_host import CaiXiHuiHost

    folder = tempfile.mkdtemp(prefix='cixi_skill_routing_')
    return AgentWorkspace(CaiXiHuiHost(data_dir=Path(folder) / 'ai', lang='zh'))


def measure(workspace=None) -> list[dict]:
    """One row per task: what the router chose and whether the table accepts it."""
    workspace = workspace or _workspace()
    rows = []
    for task in TASKS:
        chosen = workspace.skills.route(task['prompt'], 'default')
        rows.append(
            {
                'id': task['id'],
                'prompt': task['prompt'],
                'expected': list(task['skills']),
                'chosen': chosen,
                'ok': chosen in task['skills'],
            },
        )
    return rows


def report(rows: list[dict]) -> str:
    lines = ['# 自动技能路由评测', '']
    passed = sum(1 for row in rows if row['ok'])
    lines.append(f'命中 **{passed} / {len(rows)}**（确定性路由，不需要模型）。')
    lines.extend(['', '| 提问 | 期望 | 选中 | 结果 |', '|---|---|---|---|'])
    for row in rows:
        lines.append(
            f'| {row["prompt"]} | {", ".join(row["expected"])} | {row["chosen"]} | {"ok" if row["ok"] else "MISS"} |',
        )
    misses = [row for row in rows if not row['ok']]
    if misses:
        lines.extend(['', '## 未命中', ''])
        lines.extend(f'- {row["prompt"]} → {row["chosen"]}（期望 {", ".join(row["expected"])}）' for row in misses)
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Score the automatic skill router against a fixed table.')
    parser.add_argument('--json', default='', help='write the rows here as JSON')
    arguments = parser.parse_args(argv)
    rows = measure()
    page = report(rows)
    print(page)
    if arguments.json:
        destination = Path(arguments.json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if all(row['ok'] for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
