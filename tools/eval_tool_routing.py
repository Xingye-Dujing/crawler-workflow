"""Which tool would the model pick? A small, local, repeatable routing eval.

The AI workspace hands the model a list of tool names and one-sentence descriptions and expects it to
choose — so the quality of those DESCRIPTIONS is a measurable thing, not an opinion. This script asks
a local Ollama model the same 26 user utterances and scores the tool name it answers with.

It is deliberately not part of pytest: it needs a model, it is slow, and its numbers are a reading,
not a pass/fail. `docs/testing/model-eval.md` records the runs.

    python tools/eval_tool_routing.py                      # qwen3.5:4b
    python tools/eval_tool_routing.py --model qwen3.5:9b --model qwen3.5:2b
    python tools/eval_tool_routing.py --json docs/testing/model-eval.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'backend'))

#: One line per task: what the user said, and the tools that are a correct answer (a couple of these
#: genuinely have two right answers, and scoring one of them wrong would measure the eval, not the model).
TASKS = (
    {
        'id': 'count-with-filter',
        'prompt': '这个数据集里提到“旅游”的评论一共有多少条？给我准确数字。',
        'expect': ('dataset_query',),
    },
    {
        'id': 'peek-first',
        'prompt': 'ds_1 这个数据集长什么样？先给我几行看看。',
        'expect': ('dataset_peek', 'dataset_profile'),
    },
    {
        'id': 'schema',
        'prompt': 'ds_1 有哪些列，每列是什么类型，缺多少值？',
        'expect': ('dataset_profile',),
    },
    {
        'id': 'page',
        'prompt': '把 ds_1 从第 200 行开始的 50 行给我。',
        'expect': ('dataset_page', 'dataset_sample'),
    },
    {
        'id': 'list-datasets',
        'prompt': '我这个账号里有哪些数据集？',
        'expect': ('list_datasets',),
    },
    {
        'id': 'grant',
        'prompt': '我需要在这个会话里读 ds_1 最多两千行，帮我申请一下授权。',
        'expect': ('request_dataset_access',),
    },
    {
        'id': 'run-failed',
        'prompt': '刚才那次运行为什么失败了？后台有没有报错？',
        'expect': ('app_errors', 'run_status'),
    },
    {
        'id': 'run-nodes',
        'prompt': '看一下 run_abc 每个节点都是什么状态。',
        'expect': ('run_status',),
    },
    {
        'id': 'rerun',
        'prompt': '把 run_abc 里失败的那个节点和它下游重跑一遍。',
        'expect': ('rerun_node',),
    },
    {
        'id': 'workflow-list',
        'prompt': '我保存了哪些工作流？',
        'expect': ('workflow_list',),
    },
    {
        'id': 'workflow-validate',
        'prompt': '先帮我校验一下这个工作流草稿能不能跑，有没有问题。',
        'expect': ('workflow_validate',),
    },
    {
        'id': 'workflow-run',
        'prompt': '把保存的“热门榜”这个工作流跑起来。',
        'expect': ('workflow_run',),
    },
    {
        'id': 'workflow-stop',
        'prompt': '停一下现在正在跑的那个采集。',
        'expect': ('workflow_stop',),
    },
    {
        'id': 'workflow-delete',
        'prompt': '把“旧草稿”这个工作流删掉。',
        'expect': ('workflow_delete',),
    },
    {
        'id': 'workflow-export',
        'prompt': '把“热门榜”导出成一个项目包，我要下载。',
        'expect': ('workflow_export',),
    },
    {
        'id': 'export-list',
        'prompt': '我导出过的文件都有哪些？',
        'expect': ('export_list',),
    },
    {
        'id': 'models-catalog',
        'prompt': '这台机器能跑哪些情感分析模型？哪个质量最好？',
        'expect': ('models_catalog',),
    },
    {
        'id': 'model-infer',
        'prompt': '用情感模型给这 20 条评论打分，只跑这 20 条。',
        'expect': ('model_infer',),
    },
    {
        'id': 'rerank',
        'prompt': '把这三条候选按它们和“三亚旅游”的相关性排个序。',
        'expect': ('model_rerank',),
    },
    {
        'id': 'chart-contract',
        'prompt': '主题距离图需要哪些列？',
        'expect': ('chart_catalog',),
    },
    {
        'id': 'ops',
        'prompt': '这个系统一共支持哪些分析算子？',
        'expect': ('analysis_catalog',),
    },
    {
        'id': 'code-read',
        'prompt': '读一下 backend/ai/tools/datasets.py 的前 80 行。',
        'expect': ('code_read',),
    },
    {
        'id': 'code-search',
        'prompt': '搜一下代码里哪里调用了 stop_run。',
        'expect': ('code_search',),
    },
    {
        'id': 'catbus',
        'prompt': 'CatBus 在这台机器上装好了吗？我只想看状态，不要安装。',
        'expect': ('catbus_status',),
    },
    {
        'id': 'skills',
        'prompt': '列出所有能力技能，我要找和图表的有关的。',
        'expect': ('skill_catalog',),
    },
    {
        'id': 'skill-load',
        'prompt': '把 dataset_query 这个能力技能的完整正文读出来。',
        'expect': ('skill_load',),
    },
)


def catalogue_lines() -> str:
    """The offer list, built from the shipped catalogue — the thing this eval measures."""
    from ai.tools import TOOLS

    lines = []
    for name in sorted(TOOLS):
        first = str(TOOLS[name].description or '').split('. ')[0].strip()
        lines.append(f'- {name}: {first}')
    return '\n'.join(lines)


def build_prompt(text: str) -> str:
    control = (
        '- ask_user_question: ask the user to choose among options\n'
        '- update_plan: show a short plan\n'
        '- present_artifact: propose an artifact the user applies\n'
        '- request_approval: ask for approval of one exact mutating call\n'
    )
    return (
        'You are choosing exactly ONE tool to answer the user. Reply with the tool name only.\n\n'
        f'Tools:\n{catalogue_lines()}\n{control}\n'
        f'User: {text}\nTool:'
    )


def parse_tool(answer: str, known) -> str:
    """The first known tool name in the answer; '' when the model answered prose instead."""
    text = str(answer or '')
    for match in re.finditer(r'[a-z][a-z0-9_]{2,}', text):
        if match.group(0) in known:
            return match.group(0)
    return ''


def run_model(model: str, limit: int = 0, temperature: float = 0.1) -> dict:
    from ai.tools import TOOLS

    from analyzers.llm_client import LLMClient, LLMError

    known = set(TOOLS) | {'ask_user_question', 'update_plan', 'present_artifact', 'request_approval'}
    client = LLMClient(provider='ollama', model=model, temperature=temperature, max_tokens=64)
    tasks = TASKS[:limit] if limit else TASKS
    results = []
    for task in tasks:
        try:
            answer = client.chat(build_prompt(task['prompt']))
        except LLMError as exc:
            return {'model': model, 'error': f'{exc} — is `ollama serve` running and {model} pulled?', 'results': []}
        picked = parse_tool(answer, known)
        results.append(
            {
                'id': task['id'],
                'expected': list(task['expect']),
                'picked': picked,
                'ok': picked in task['expect'],
                'answer': str(answer or '').strip()[:120],
            }
        )
    correct = sum(1 for row in results if row['ok'])
    return {'model': model, 'correct': correct, 'total': len(results), 'results': results}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--model', action='append', default=[], help='Ollama model tag; repeatable')
    parser.add_argument('--limit', type=int, default=0, help='only the first N tasks')
    parser.add_argument('--temperature', type=float, default=0.1)
    parser.add_argument('--json', default='', help='write the full results here')
    args = parser.parse_args(argv)

    models = args.model or ['qwen3.5:4b']
    reports = []
    for model in models:
        report = run_model(model, limit=args.limit, temperature=args.temperature)
        reports.append(report)
        if report.get('error'):
            print(f'{model}: {report["error"]}')
            continue
        print(f'{model}: {report["correct"]}/{report["total"]} correct')
        for row in report['results']:
            if not row['ok']:
                print(f'  x {row["id"]}: expected {row["expected"]}, picked {row["picked"] or "(prose)"}')
    if args.json:
        Path(args.json).write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'wrote {args.json}')
    return 0 if any(not report.get('error') for report in reports) else 1


if __name__ == '__main__':
    raise SystemExit(main())
