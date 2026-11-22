"""The source capability: one platform crawl, configured by the platform matrix.

A source node has no fixed parameter list. Which fields it offers depends on the platform, the
engine and the mode the user picked, and that matrix lives in ``capabilities/platforms/<id>.py``.
The manifest therefore declares no params and points the client at that matrix
(``ui.defaults_from='capabilities'``); its pre-run check lives with the executor because it has to
read the same matrix (feed shape, required fields, session, link ownership).
"""

from capabilities_kernel.manifest import (
    Ai,
    Docs,
    Execution,
    Identity,
    Manifest,
    Ports,
    Tests,
    Ui,
)

MANIFEST = Manifest(
    identity=Identity(
        id='source',
        kind='node',
        version='1.0.0',
        title_key='nodeType.source',
        category='data',
        order=1,
        description='Crawl one platform in one mode and emit its rows.',
        when_to_use='When the corpus is a platform search, a board, an author page or a link list.',
    ),
    params=(),
    ports=Ports(rows='table', inputs=1),
    execution=Execution(handler='nodes.executors.source:run'),
    validators=('nodes.executors.source:validate_node',),
    ui=Ui(form='custom', custom_renderer='source', defaults_from='capabilities'),
    ai=Ai(
        summary=(
            '数据源 crawls one platform with one mode and emits that mode’s table (a search, a board, '
            'an author page, a note/article list, or one link list). The platform matrix decides the '
            'fields, the required values and whether the mode needs a saved login.'
        ),
        steps=(
            'Pick a platform, then an engine (Selenium or CatBus) and a mode; the form shows that cell’s fields.',
            'Fill the mode’s required fields (a keyword, a board, a link list or an author link).',
            'Pick the login account when the mode needs a session; anonymous modes are not asked.',
        ),
        examples=(
            {
                'type': 'source',
                'params': {
                    'platform': 'weibo',
                    'mode': 'search',
                    'keyword': '人工智能',
                    'target_count': 100,
                    'account': 'default',
                },
            },
        ),
        failures=(
            'No platform: engine.source_no_platform.',
            'A platform/mode this matrix does not offer: engine.source_unknown_platform / _unknown_mode.',
            'A missing required field: engine.source_missing; a value off the offered list: engine.source_bad_option.',
            'A session-required mode whose account holds no login: the preflight keys.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_source_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/source.md'),
)
