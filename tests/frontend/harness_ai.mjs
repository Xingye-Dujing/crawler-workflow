/* Drives the real AI stream decoder and safe renderer without a browser or a network. */
import fs from 'node:fs';
import vm from 'node:vm';

const root = process.argv[2];
const read = (name) => fs.readFileSync(`${root}/${name}`, 'utf8');
const sandbox = {
    console,
    TextDecoder,
    ReadableStream,
    window: {},
    I18n: { t: (key) => key },
    fetch: async () => new Response(
        new ReadableStream({
            start(controller) {
                controller.enqueue(new TextEncoder().encode('data: {"type":"text","text":"hello"}\n\n'));
                controller.enqueue(new TextEncoder().encode(': keep-alive\n\n'));
                controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\n'));
                controller.close();
            },
        }),
        { headers: { 'Content-Type': 'text/event-stream' } },
    ),
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(read('ai/render.js'), sandbox);
vm.runInContext(read('ai/stream.js'), sandbox);
vm.runInContext(read('ai-workspace.js'), sandbox);
sandbox.AISettings = { load: () => ({}) };

const events = [];
await sandbox.AIStream.post('/api/ai/chat', {}, (event) => events.push(event));

/* The runtime chip and the skill selector are the two surfaces that tell a desktop or cloud user
   what this host can do; drive the real methods rather than a copied table. */
const workspace = sandbox.AIWorkspace;
workspace._bootstrap = {
    providers: [],
    runtime: { kind: 'desktop', label_key: 'ai.runtime.desktop', ollama: true, user_files: true, local_source: false, code_plugins: true },
    skills: [{ id: 'developer', name: 'Developer', available: false, why_not_text: 'needs the repository source' }],
};
workspace._dom.skill = { innerHTML: '' };
workspace._renderSkillOptions();
const skillOptions = workspace._dom.skill.innerHTML;
workspace._bootstrap.providers = [
    { id: 'deepseek', label_key: 'ai.provider.deepseek', local_available: true, models: [{ id: 'deepseek-flash', label: 'Flash' }] },
    { id: 'ollama', label_key: 'ai.provider.ollama', local_available: false, why_not_text: 'no local daemon on a cloud host', models: [] },
];
workspace._dom.provider = { innerHTML: '' };
workspace._dom.model = { innerHTML: '' };
workspace._dom.modelChip = { textContent: '' };
workspace._renderProviderOptions();
const providerOptions = workspace._dom.provider.innerHTML;

const out = {
    events,
    escapedScript: sandbox.AIRender.markdown('<script>alert(1)</script>'),
    escapedLink: sandbox.AIRender.markdown('[x](javascript:alert(1))'),
    safeLink: sandbox.AIRender.markdown('[ok](https://example.com/a)'),
    question: sandbox.AIRender.questionCard({ id: 'q1', question: 'Pick <b>', options: [{ label: 'A' }] }, false),
    artifact: sandbox.AIRender.artifactCard({ id: 'a1', title: 'Draft', kind: 'workflow_draft', payload: { nodes: [] } }),
    runtimeTitle: workspace._runtimeTitle(),
    skillOptions,
    providerOptions,
};
process.stdout.write(JSON.stringify(out));
