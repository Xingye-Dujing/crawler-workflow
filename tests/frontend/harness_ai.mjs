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

const events = [];
await sandbox.AIStream.post('/api/ai/chat', {}, (event) => events.push(event));
const out = {
    events,
    escapedScript: sandbox.AIRender.markdown('<script>alert(1)</script>'),
    escapedLink: sandbox.AIRender.markdown('[x](javascript:alert(1))'),
    safeLink: sandbox.AIRender.markdown('[ok](https://example.com/a)'),
    question: sandbox.AIRender.questionCard({ id: 'q1', question: 'Pick <b>', options: [{ label: 'A' }] }, false),
    artifact: sandbox.AIRender.artifactCard({ id: 'a1', title: 'Draft', kind: 'workflow_draft', payload: { nodes: [] } }),
};
process.stdout.write(JSON.stringify(out));
