// Run with: node scripts/test-match-state.mjs
// Bundle the real stores; only HTTP and independent mock data are controlled.
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

// Resolve Vite's declared esbuild dependency under both npm and strict pnpm layouts.
const require = createRequire(import.meta.url)
const viteRequire = createRequire(require.resolve('vite'))
const { build } = await import(pathToFileURL(viteRequire.resolve('esbuild')).href)
const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const temporaryDirectory = await mkdtemp(join(tmpdir(), 'tsing-radar-match-state-'))
const stubs = {
  '@/api/advisor': `
    export const requests = [];
    export const scatterRequests = [];
    export function matchAdvisors(request, signal) {
      return new Promise((resolve, reject) => requests.push({ request, signal, resolve, reject }));
    }
    export function fetchScatter() {
      return new Promise((resolve, reject) => scatterRequests.push({ resolve, reject }));
    }
  `,
  '@/mock': 'export const mockScatterPoints = []; export const mockChatReply = () => "";',
  '@/api/chat': 'export function streamChat() { throw new Error("unexpected chat HTTP request"); }',
  '@/api/interview': `
    export function confirmInterviewProfile() { throw new Error('unexpected confirm HTTP request'); }
    export function editInterviewProfile() { throw new Error('unexpected edit HTTP request'); }
  `,
}

const entry = `
  import assert from 'node:assert/strict';
  import { test } from 'node:test';
  import { createPinia, disposePinia, setActivePinia } from 'pinia';
  import { nextTick } from 'vue';
  import { useAdvisorStore } from '@/stores/useAdvisorStore';
  import { useChatStore } from '@/stores/useChatStore';
  import { requests, scatterRequests } from '@/api/advisor';

  const response = (id) => ({
    data: [{ advisor_id: id, name: '同名导师', score: 50 }],
    status: 'matched', message: 'matched ' + id, meta: {},
  });
  async function flush() { await nextTick(); await Promise.resolve(); await nextTick(); }
  function fixture() {
    const pinia = createPinia();
    setActivePinia(pinia);
    requests.length = 0;
    scatterRequests.length = 0;
    const chat = useChatStore();
    const advisor = useAdvisorStore();
    const confirm = (session = 'session-a', version = 1) => chat.$patch({
      sessionId: session, profileVersion: version,
      interviewStatus: 'confirmed', recommendReady: true,
    });
    return { chat, advisor, confirm, dispose: () => disposePinia(pinia) };
  }

  await test('confirmation starts matching once; homepage resource loading preserves results', async () => {
    const f = fixture();
    try {
      f.chat.$patch({ sessionId: 'session-a', profileVersion: 1 });
      await flush();
      assert.equal(requests.length, 0);
      f.confirm();
      await flush();
      assert.equal(requests.length, 1);
      assert.deepEqual(requests[0].request, { session_id: 'session-a' });
      requests[0].resolve(response('mentor-a'));
      await flush();
      f.advisor.selectAdvisor('mentor-a');
      const publicLoading = f.advisor.loadAll();
      assert.equal(f.advisor.loading, false);
      scatterRequests[0].resolve({ data: [] });
      await publicLoading;
      assert.equal(f.advisor.totalCount, 1);
      assert.equal(f.advisor.selectedAdvisor.advisor_id, 'mentor-a');
      assert.equal(f.advisor.resultStatus, 'matched');
      assert.equal(requests.length, 1);
    } finally { f.dispose(); }
  });

  await test('new conversation invalidates a pending match even if transport ignores abort', async () => {
    const f = fixture();
    try {
      f.confirm();
      await flush();
      const previous = requests[0];
      f.chat.newConversation();
      f.advisor.resetResults();
      assert.equal(previous.signal.aborted, true);
      previous.resolve(response('old-mentor'));
      await flush();
      assert.equal(f.advisor.totalCount, 0);
      assert.equal(f.advisor.resultStatus, 'idle');
      assert.equal(f.advisor.loading, false);
      assert.equal(f.advisor.canRetry, false);
    } finally { f.dispose(); }
  });

  await test('new profile version owns results and loading; stale error cannot replace it', async () => {
    const f = fixture();
    try {
      f.confirm();
      await flush();
      const old = requests[0];
      f.confirm('session-a', 2);
      await flush();
      assert.equal(requests.length, 2);
      assert.equal(old.signal.aborted, true);
      const scatter = f.advisor.loadAll();
      scatterRequests[0].resolve({ data: [] });
      await scatter;
      assert.equal(f.advisor.loading, true);
      old.reject(new Error('old failure'));
      await flush();
      assert.equal(f.advisor.loading, true);
      assert.notEqual(f.advisor.resultStatus, 'error');
      requests[1].resolve(response('new-mentor'));
      await flush();
      assert.equal(f.advisor.matchedAdvisors[0].advisor_id, 'new-mentor');
      assert.equal(f.advisor.loading, false);
    } finally { f.dispose(); }
  });

  await test('late response after a session switch cannot write before watcher runs', async () => {
    const f = fixture();
    try {
      f.confirm();
      await flush();
      f.confirm('session-b', 1);
      requests[0].resolve(response('old-session'));
      await flush();
      assert.equal(f.advisor.totalCount, 0);
      requests[1].resolve(response('new-session'));
      await flush();
      assert.equal(f.advisor.matchedAdvisors[0].advisor_id, 'new-session');
    } finally { f.dispose(); }
  });

  await test('transient failure can retry the same confirmed profile without editing it', async () => {
    const f = fixture();
    try {
      f.confirm();
      await flush();
      requests[0].reject(new Error('network unavailable'));
      await flush();
      assert.equal(f.advisor.resultStatus, 'error');
      assert.equal(f.advisor.canRetry, true);
      const retry = f.advisor.retryMatch();
      assert.equal(requests.length, 2);
      requests[1].resolve(response('retry-mentor'));
      await retry;
      assert.equal(f.advisor.totalCount, 1);
      assert.equal(f.advisor.canRetry, false);
    } finally { f.dispose(); }
  });

  await test('editing a confirmed profile invalidates recommendations until reconfirmed', async () => {
    const f = fixture();
    try {
      f.confirm();
      await flush();
      requests[0].resolve(response('mentor-a'));
      await flush();
      f.chat.$patch({ interviewStatus: 'awaiting_confirmation', recommendReady: false, profileVersion: 2 });
      await flush();
      assert.equal(f.advisor.totalCount, 0);
      assert.equal(f.advisor.resultStatus, 'idle');
      assert.equal(requests.length, 1);
    } finally { f.dispose(); }
  });

  await test('same-name mentors remain distinct by ID; ambiguous legacy names select neither', async () => {
    const f = fixture();
    try {
      f.confirm();
      await flush();
      const result = response('mentor-a');
      result.data.push({ advisor_id: 'mentor-b', name: '同名导师', score: 40 });
      requests[0].resolve(result);
      await flush();
      f.advisor.selectAdvisor('mentor-b');
      assert.equal(f.advisor.selectedAdvisor.advisor_id, 'mentor-b');
      f.advisor.selectAdvisor('同名导师');
      assert.equal(f.advisor.selectedAdvisor, null);
    } finally { f.dispose(); }
  });
`

try {
  const result = await build({
    stdin: { contents: entry, resolveDir: frontendRoot, loader: 'ts' },
    bundle: true,
    platform: 'node',
    format: 'esm',
    write: false,
    define: { 'import.meta.env.VITE_USE_MOCK': '"false"' },
    plugins: [{
      name: 'controlled-http',
      setup(builder) {
        builder.onResolve({ filter: /^@\// }, (args) => {
          if (args.path in stubs) return { path: args.path, namespace: 'http-stub' }
          return { path: resolve(frontendRoot, 'src', args.path.slice(2) + '.ts') }
        })
        builder.onLoad({ filter: /.*/, namespace: 'http-stub' }, (args) => ({
          contents: stubs[args.path], loader: 'js',
        }))
      },
    }],
  })
  const bundlePath = join(temporaryDirectory, 'match-state-tests.mjs')
  await writeFile(bundlePath, result.outputFiles[0].text)
  await import(pathToFileURL(bundlePath).href)
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true })
}
