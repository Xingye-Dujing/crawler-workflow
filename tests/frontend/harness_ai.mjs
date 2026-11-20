/* Drives the REAL AI stream decoder and safe renderer without a browser or a network.
 *
 * The page's own loader supplies the files (index.html order) and the real i18n catalogue, so a
 * split-out companion or a moved dictionary word cannot quietly leave this harness measuring an
 * app the page does not ship. Usage: node harness_ai.mjs <jsDir>
 */
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { loadPageScripts } from './page_scripts.mjs';

const root = process.argv[2];
const sandbox = baseSandbox();
/* The stream decoder needs the platform's web primitives; node has them, the stub page does not. */
sandbox.TextDecoder = TextDecoder;
sandbox.TextEncoder = TextEncoder;
sandbox.Response = Response;
sandbox.ReadableStream = ReadableStream;
vm.createContext(sandbox);
fixWindow(vm, sandbox);
loadPageScripts(sandbox, { jsDir: root, only: ['app.js', 'ai-workspace.js'] });

/* The transport is the one thing replaced: the server's SSE bytes are a fixture, not product code. */
sandbox.fetch = async () =>
    new Response(
        new ReadableStream({
            start(controller) {
                controller.enqueue(new TextEncoder().encode('data: {"type":"text","text":"hello"}\n\n'));
                controller.enqueue(new TextEncoder().encode(': keep-alive\n\n'));
                controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n'));
                controller.close();
            },
        }),
        { headers: { 'Content-Type': 'text/event-stream' } },
    );

const events = [];
await sandbox.AIStream.post('/api/ai/chat', {}, (event) => events.push(event));

/* The runtime chip and the skill selector are the two surfaces that tell a desktop or cloud user
   what this host can do; drive the real methods rather than a copied table. */
const workspace = sandbox.AIWorkspace;
const I18n = vm.runInContext('I18n', sandbox);
I18n.lang = 'en';
workspace._bootstrap = {
    providers: [],
    runtime: {
        kind: 'desktop',
        label_key: 'ai.runtime.desktop',
        ollama: true,
        user_files: true,
        local_source: false,
        code_plugins: true,
    },
    skills: [{ id: 'developer', name: 'Developer', available: false, why_not_text: 'needs the repository source' }],
};
workspace._dom.skill = sandbox.document.getElementById('ai-skill');
workspace._renderSkillOptions();
const skillOptions = workspace._dom.skill.innerHTML;
workspace._bootstrap.providers = [
    { id: 'deepseek', label_key: 'ai.provider.deepseek', local_available: true, models: [{ id: 'deepseek-flash', label: 'Flash' }] },
    { id: 'ollama', label_key: 'ai.provider.ollama', local_available: false, why_not_text: 'no local daemon on a cloud host', models: [] },
];
workspace._dom.provider = sandbox.document.getElementById('ai-ws-provider');
workspace._dom.model = sandbox.document.getElementById('ai-ws-model');
workspace._dom.modelChip = sandbox.document.getElementById('ai-model-chip');
workspace._renderProviderOptions();
const providerOptions = workspace._dom.provider.innerHTML;

/* A node trace conversation must move the bottom chip to the model the NODE actually used. */
const previousFetch = sandbox.fetch;
sandbox.fetch = async () =>
    new Response(
        JSON.stringify({
            ok: true,
            conversation: {
                id: 'c_trace',
                provider: 'ollama',
                model: 'qwen3.5:2b',
                skill: 'node_trace',
                title: 'trace',
            },
            messages: [],
            pending_questions: [],
        }),
        { headers: { 'Content-Type': 'application/json' } },
    );
await workspace.selectConversation('c_trace');
sandbox.fetch = previousFetch;
const traceChip = workspace._dom.modelChip.textContent;
const traceChipTitle = workspace._dom.modelChip.title;

const out = {
    events,
    lang: I18n.lang,
    escapedScript: sandbox.AIRender.markdown('<script>alert(1)</script>'),
    escapedLink: sandbox.AIRender.markdown('[x](javascript:alert(1))'),
    safeLink: sandbox.AIRender.markdown('[ok](https://example.com/a)'),
    /* A pipe inside inline code and an escaped pipe are CELLS, not column breaks. This is the row
       that used to render as two extra cells with a stray "连接，groupby_agg` 不会展开". */
    tablePipes: sandbox.AIRender.markdown(
        '| 步骤 | 做法 |\n| --- | --- |\n| 图 7 | 多重编码用 `a|b` 连接 |\n| 图 8 | 用 \\| 连接，`groupby_agg` 不会展开 |\n'
    ),
    question: sandbox.AIRender.questionCard({ id: 'q1', question: 'Pick <b>', options: [{ label: 'A' }] }, false),
    artifact: sandbox.AIRender.artifactCard({ id: 'a1', title: 'Draft', kind: 'workflow_draft', payload: { nodes: [] } }),
    runtimeTitle: workspace._runtimeTitle(),
    skillOptions,
    providerOptions,
    traceChip,
    traceChipTitle,
    hasKnown: I18n.has('ai.title'),
    hasUnknown: I18n.has('ai.notAKey'),
    turnFlow: (() => {
        /* One turn is a SEQUENCE: the skill that answered, its reasoning, its tools, its plan, the
           answer. The live view and a reopened one read the same blocks, so this text is the
           definition of "the order the model produced" for the whole workspace. */
        const html = sandbox.AIRender.assistantFlow([
            { type: 'skill', name: 'workflow', reason: 'auto' },
            { type: 'thinking', thinking: 'read the canvas first' },
            { type: 'tool_use', id: 't1', name: 'project_facts', input: {}, status: 'done', result: { ok: true } },
            { type: 'plan', steps: [{ title: '读画布', status: 'done' }, { title: '写草案', status: 'pending' }] },
            { type: 'text', text: 'done' },
        ]);
        const at = (needle) => html.indexOf(needle);
        return {
            skill: at('ai-skill-row'),
            thinking: at('ai-thinking'),
            tool: at('ai-tool'),
            plan: at('ai-plan-step'),
            text: at('ai-text'),
            ordered: at('ai-skill-row') < at('ai-thinking') && at('ai-thinking') < at('ai-tool') && at('ai-tool') < at('ai-plan-step') && at('ai-plan-step') < at('ai-text'),
            working: sandbox.AIRender.statusRow().includes('ai-working-dot'),
        };
    })(),
};
process.stdout.write(JSON.stringify(out));
