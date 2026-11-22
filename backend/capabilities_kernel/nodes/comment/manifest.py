"""The comment capability: article links in, comment rows out, batch by batch.

A comment crawl is always a logged-in one — its rate limit is per ACCOUNT — and one node walks
several feeds with the single account on its form. So the pre-run check is two questions: are
there links at all, and can the named account log into every platform those links name (asked of
``sessions.preflight``, where session facts live).
"""

from capabilities_kernel.manifest import (
    Ai,
    Docs,
    Execution,
    Identity,
    Manifest,
    ParamSpec,
    Ports,
    Rule,
    Tests,
    Ui,
)

MANIFEST = Manifest(
    identity=Identity(
        id='comment',
        kind='node',
        version='1.0.0',
        title_key='nodeType.comment',
        category='data',
        order=4,
        description='Crawl the comments of article links (or 红果 titles) into one row table.',
        when_to_use='When the post table is known and the comments under each post are the corpus.',
    ),
    params=(
        ParamSpec(name='urls', type='string', default='', required=True, widget='textarea'),
        ParamSpec(name='comment_limit', type='integer', default=0, minimum=0, widget='number'),
        ParamSpec(name='part_size', type='integer', default=50, minimum=0, widget='number'),
        ParamSpec(name='per_article_file', type='boolean', default=True, widget='switch'),
        ParamSpec(name='keep_parts', type='boolean', default=False, widget='switch'),
        ParamSpec(name='recrawl', type='boolean', default=False, widget='switch'),
        ParamSpec(name='format', type='string', default='csv', enum=('csv', 'json'), widget='select'),
    ),
    ports=Ports(rows='table', inputs=0),
    execution=Execution(handler='nodes.executors.comment:run'),
    rules=(
        Rule(
            kind='required_param',
            code='engine.comment_no_urls',
            message_key='engine.comment_no_urls',
            param='urls',
        ),
    ),
    validators=('nodes.executors.comment:validate_node',),
    ui=Ui(form='custom', custom_renderer='comment'),
    ai=Ai(
        summary=(
            '评论采集 walks the comments of the article links on one form, batch by batch, and emits the '
            'same comment table a 数据源 in comments mode produces (评论内容/评论时间/点赞数/文章URL …). '
            'The cursor records only the leading links it PROVED complete, so 继续 replays from the first hole.'
        ),
        steps=(
            'Paste article links (one per line); a 红果 title is accepted where the matrix declares names.',
            'Pick the login account — the comment wall is a per-account rate limit, which is why accounts exist.',
            'Set comment_limit (0 = every comment), part_size and whether parts are kept.',
        ),
        examples=(
            {
                'type': 'comment',
                'params': {
                    'urls': 'https://www.zhihu.com/question/1/answer/2',
                    'comment_limit': 0,
                    'part_size': 50,
                    'per_article_file': True,
                    'keep_parts': False,
                    'recrawl': False,
                    'format': 'csv',
                },
            },
        ),
        failures=(
            'No links: engine.comment_no_urls.',
            'The account holds no login for a platform a link names: engine.source_no_cookie_account.',
            'A @pool account with no saved login / all cooling: engine.source_pool_empty / _cooling.',
            'A walled or short link settles PARTIAL and keeps its cursor hole, so 继续 re-walks it.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_comment_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/comment.md'),
)
