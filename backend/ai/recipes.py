"""The product's recipes: ordered plans whose steps need server evidence.

A recipe is data the framework turns into a durable run: each step names one tool and the earlier
steps whose evidence it requires. The model cannot skip ahead because the framework offers only the
current step's tool plus read-only tools, and a step is done only when its tool result exists.

These are deliberately few and generic. A per-node recipe belongs with that node's capability skill
(P7); this module holds the two cross-node jobs every user starts with.
"""

from __future__ import annotations

RECIPES = (
    {
        'id': 'workflow_build',
        'title': '建一条可运行的工作流',
        'steps': [
            {
                'id': 'schema',
                'title': '读节点/参数/平台词汇',
                'tool': 'workflow_schema',
                'produces': 'schema',
            },
            {
                'id': 'propose',
                'title': '提交工作流产物卡',
                'tool': 'present_artifact',
                'requires': ['schema'],
                'produces': 'workflow',
            },
            {
                'id': 'validate',
                'title': '用同一引擎校验',
                'tool': 'workflow_validate',
                'requires': ['propose'],
                'produces': 'validation',
            },
        ],
    },
    {
        'id': 'dataset_answer',
        'title': '用一个数据集回答一个精确数字',
        'steps': [
            {
                'id': 'profile',
                'title': '读列名、类型与行数',
                'tool': 'dataset_profile',
                'produces': 'profile',
            },
            {
                'id': 'peek',
                'title': '读前几行确认含义',
                'tool': 'dataset_peek',
                'requires': ['profile'],
                'produces': 'sample',
            },
            {
                'id': 'query',
                'title': '用聚合算子得到精确值',
                'tool': 'dataset_query',
                'requires': ['peek'],
                'produces': 'answer',
            },
        ],
    },
)


def catalog() -> list[dict]:
    """The level-1 list the project context and the API show."""
    return [
        {
            'id': recipe['id'],
            'title': recipe['title'],
            'steps': [{'id': step['id'], 'title': step['title'], 'tool': step['tool']} for step in recipe['steps']],
        }
        for recipe in RECIPES
    ]
