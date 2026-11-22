"""The biblio capability: bibliometric networks, tables and monitors over a record table.

One node carries the whole bibliometric surface — entity/co-occurrence/coupling networks, the
selection and pruning rules, cluster labelling, burst detection, structural variation, the output
shape (nodes/edges/clusters/bursts/variation/dual_map) and the cross-run monitor.

The 56 parameters and their option lists are declared here, and ``services.biblio.schema`` derives
its ``DEFAULTS``/option tuples from this manifest: one declaration, read by the validator, the
form, the generated catalogue and the run. Range checks (a whole number inside low..high) are NOT
expressed as ``minimum``/``maximum`` here — the validator already refuses them by name with the
parameter that caused it, and a second copy would be a number that can drift.
"""

from capabilities_kernel.manifest import (
    Ai,
    Docs,
    Execution,
    Identity,
    Manifest,
    ParamSpec,
    Ports,
    Tests,
    Ui,
)

#: The entity kinds a network can be built from. The last six name a cited/citing unit rather
#: than an attribute of the record (co-citation, coupling); ``document`` and
#: ``bibliographic_coupling`` are the same construction under two communities' names.
ENTITY_TYPES = (
    'keyword',
    'author',
    'institution',
    'country',
    'term',
    'category',
    'journal',
    'source',
    'funder',
    'grant',
    'document_cocitation',
    'author_cocitation',
    'journal_cocitation',
    'article',
    'document',
    'bibliographic_coupling',
)

OUTPUT_SHAPES = ('nodes', 'edges', 'clusters', 'bursts', 'variation', 'dual_map')
SELECTION_MODES = ('top_n', 'top_pct', 'g_index', 'threshold')
LINK_MEASURES = ('cosine', 'dice', 'jaccard', 'association')
#: How much a mediating document contributes to a link: ``full`` counts it once per pair it
#: contains; ``fractional`` divides its credit across the entries it carries, so one article with
#: 150 references stops outranking one with 12.
COUNTING_MODES = ('full', 'fractional')
PRUNING_MODES = ('none', 'mst', 'pathfinder')
PRUNING_SCOPES = ('slices', 'merged')
#: Mantel's r-norm exponent for the Pathfinder reduction. ``inf`` is the classic PFNET (a path is
#: as long as its weakest link), ``1`` sums link distances, ``2`` takes their Euclidean norm.
#: Stored as a string because the setting is a select, and ``inf`` never becomes a float in JSON.
PATHFINDER_R = ('1', '2', 'inf')
LABEL_METHODS = ('llr', 'lsi', 'mi', 'tfidf')
#: Which fields a cluster label draws its words from; ``all`` is the historical mix and
#: deliberately excludes author names.
LABEL_SOURCES = ('all', 'title', 'abstract', 'keywords', 'author')

MANIFEST = Manifest(
    identity=Identity(
        id='biblio',
        kind='node',
        version='1.0.0',
        title_key='nodeType.biblio',
        category='biblio',
        order=9,
        description='Build a bibliometric network/table (co-occurrence, coupling, bursts) from records.',
        when_to_use='After 文献融合 or a CNKI import, when the records should become a citation/co-word map.',
    ),
    params=(
        # ─── Entity and column mapping ───
        ParamSpec(name='entity_type', type='string', default='keyword', enum=ENTITY_TYPES, widget='select'),
        # A blank entity column means "the canonical column for this kind" (关键词/作者/…); every
        # other blank means its canonical name. A crawled table can map 话题/用户名/发布时间 here.
        ParamSpec(name='entity_column', type='string', default='', widget='column'),
        ParamSpec(name='year_column', type='string', default='年份', widget='column'),
        ParamSpec(name='title_column', type='string', default='题名', widget='column'),
        ParamSpec(name='abstract_column', type='string', default='摘要', widget='column'),
        ParamSpec(name='reference_column', type='string', default='参考文献', widget='column'),
        ParamSpec(name='tc_column', type='string', default='引用次数', widget='column'),
        ParamSpec(name='usage_column', type='string', default='使用次数', widget='column'),
        # Optional overlays of a label column an upstream step already wrote. Blank = the node
        # behaves exactly as before these parameters existed; a NAMED absent column is refused.
        ParamSpec(name='sentiment_column', type='string', default='', widget='column'),
        ParamSpec(name='topic_column', type='string', default='', widget='column'),
        ParamSpec(name='time_start', type='string', default='', widget='text'),
        ParamSpec(name='time_end', type='string', default='', widget='text'),
        ParamSpec(name='slice_years', type='integer', default=1, widget='number'),
        ParamSpec(name='look_back_years', type='integer', default=0, widget='number'),
        # ─── Selection ───
        ParamSpec(name='selection', type='string', default='top_n', enum=SELECTION_MODES, widget='select'),
        ParamSpec(name='top_n', type='integer', default=50, widget='number'),
        ParamSpec(name='top_pct', type='integer', default=10, widget='number'),
        ParamSpec(name='g_index', type='integer', default=25, widget='number'),
        ParamSpec(name='min_count', type='integer', default=2, widget='number'),
        ParamSpec(name='threshold_c', type='integer', default=0, widget='number'),
        ParamSpec(name='threshold_cc', type='integer', default=1, widget='number'),
        ParamSpec(name='threshold_ccv', type='number', default=0.0, widget='number'),
        ParamSpec(name='min_tc', type='string', default='', widget='text'),
        ParamSpec(name='min_usage', type='string', default='', widget='text'),
        ParamSpec(name='largest_component', type='boolean', default=False, widget='switch'),
        # ─── Link construction and pruning ───
        ParamSpec(name='link_measure', type='string', default='cosine', enum=LINK_MEASURES, widget='select'),
        ParamSpec(name='counting', type='string', default='full', enum=COUNTING_MODES, widget='select'),
        ParamSpec(name='citation_expansion', type='integer', default=0, widget='number'),
        ParamSpec(name='max_links_per_node', type='integer', default=10, widget='number'),
        ParamSpec(name='lrf', type='number', default=2.5, widget='number'),
        ParamSpec(name='pruning', type='string', default='none', enum=PRUNING_MODES, widget='select'),
        ParamSpec(name='pruning_scope', type='string', default='slices', enum=PRUNING_SCOPES, widget='select'),
        # Pathfinder only: r is the Mantel exponent, lmax the longest indirect path considered
        # (0 = every path), dmax the fraction of surviving links to keep, strongest first.
        ParamSpec(name='pathfinder_r', type='string', default='inf', enum=PATHFINDER_R, widget='select'),
        ParamSpec(name='pathfinder_lmax', type='integer', default=0, widget='number'),
        ParamSpec(name='pathfinder_dmax', type='number', default=1.0, widget='number'),
        # ─── Clusters, labels, bursts ───
        ParamSpec(name='cluster', type='boolean', default=True, widget='switch'),
        ParamSpec(name='cluster_count', type='string', default='', widget='text'),
        ParamSpec(name='label_method', type='string', default='llr', enum=LABEL_METHODS, widget='select'),
        ParamSpec(name='label_source', type='string', default='all', enum=LABEL_SOURCES, widget='select'),
        ParamSpec(name='top_terms', type='integer', default=5, widget='number'),
        ParamSpec(name='burst', type='boolean', default=True, widget='switch'),
        ParamSpec(name='burst_gamma', type='number', default=1.0, widget='number'),
        ParamSpec(name='burst_min_duration', type='integer', default=2, widget='number'),
        ParamSpec(name='burst_weight', type='number', default=2.0, widget='number'),
        ParamSpec(name='burst_top', type='integer', default=20, widget='number'),
        # ─── Structural variation ───
        # How far a node's connection pattern moves between two consecutive slices;
        # ``variation_min`` is the divergence (in bits) a row must reach to be reported at all.
        ParamSpec(name='variation', type='boolean', default=False, widget='switch'),
        ParamSpec(name='variation_min', type='number', default=0.05, widget='number'),
        # ─── Cleaning and overlays ───
        ParamSpec(name='aliases', type='string', default='', widget='text'),
        ParamSpec(name='exclude_values', type='string', default='', widget='text'),
        ParamSpec(name='cluster_labels', type='string', default='', widget='text'),
        ParamSpec(name='basemap_dataset_id', type='string', default='', widget='dataset'),
        # ─── Cross-run monitor ───
        # Each run files its own capture and diffs it against the previous one. Blank project =
        # the node behaves exactly as before the parameter existed.
        ParamSpec(name='watch_project', type='string', default='', widget='text'),
        ParamSpec(name='watch_baseline', type='string', default='', widget='text'),
        ParamSpec(name='watch_label', type='string', default='', widget='text'),
        # ─── Output ───
        ParamSpec(name='output_shape', type='string', default='nodes', enum=OUTPUT_SHAPES, widget='select'),
        ParamSpec(name='export_files', type='boolean', default=True, widget='switch'),
    ),
    ports=Ports(
        rows='table',
        inputs=1,
        emit_columns='nodes.executors.biblio:emit_columns',
        read_columns='nodes.executors.biblio:read_columns',
    ),
    execution=Execution(handler='nodes.executors.biblio:run'),
    validators=('nodes.executors.biblio:validate_node',),
    ui=Ui(form='custom', custom_renderer='biblio'),
    ai=Ai(
        summary=(
            '文献计量 builds a bibliometric network from a record table: co-occurrence, co-citation or '
            'coupling, with slice/look-back windows, top-N/G-index/threshold selection, LRF/MST/Pathfinder '
            'pruning, cluster labels (LLR/LSI/MI/TF-IDF), burst detection, structural variation, and five '
            'output shapes (nodes/edges/clusters/bursts/variation/dual_map).'
        ),
        steps=(
            'Pick the entity type and the columns the record table really has.',
            'Choose the selection rule and the link measure; pruning is for a graph too dense to read.',
            'Pick the output shape: nodes/edges for a graph, clusters/bursts/variation for their tables, '
            'dual_map for a basemap overlay.',
        ),
        examples=(
            {
                'type': 'biblio',
                'params': {
                    'entity_type': 'keyword',
                    'time_start': '2015',
                    'time_end': '2024',
                    'slice_years': 2,
                    'selection': 'top_n',
                    'top_n': 50,
                    'link_measure': 'cosine',
                    'cluster': True,
                    'output_shape': 'nodes',
                },
            },
        ),
        failures=(
            'An option outside its list: biblio.bad_option names the parameter and the allowed values.',
            'A number outside its range: biblio.bad_option (the validator states the range).',
            'A start year after the end year: biblio.time_range.',
            'Fractional counting on a coupling network: biblio.counting_no_coupling.',
            'Bursts on a coupling network: biblio.coupling_no_burst.',
            'An output shape whose switch is off: biblio.shape_needs_cluster/burst/variation.',
            'A baseline without a project: biblio.watch_needs_project; monitoring a non-entity shape: '
            'biblio.watch_needs_entity_table.',
        ),
    ),
    tests=Tests(contracts=('tests/unit/capabilities/test_biblio_manifest.py',)),
    docs=Docs(page='docs/capabilities/nodes/biblio.md'),
)
