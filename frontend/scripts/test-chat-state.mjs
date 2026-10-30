// Run with: node scripts/test-chat-state.mjs
// Exercise the real Pinia chat store with a transport that can respond after abort.
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)
const viteRequire = createRequire(require.resolve('vite'))
const { build } = await import(pathToFileURL(viteRequire.resolve('esbuild')).href)
const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const temporaryDirectory = await mkdtemp(join(tmpdir(), 'tsing-radar-chat-state-'))
const stubs = {
  '@/api/chat': `
    export const requests = [];
    export function streamChat(payload, chunk, done, error) {
      const controller = new AbortController();
      requests.push({ payload, chunk, done, error, controller });
      return controller;
    }
  `,
  '@/api/interview': `
    export const edits = [];
    export const confirmations = [];
    export function editInterviewProfile(...args) {
      return new Promise((resolve, reject) => edits.push({ args, resolve, reject }));
    }
    export function confirmInterviewProfile(...args) {
      return new Promise((resolve, reject) => confirmations.push({ args, resolve, reject }));
    }
  `,
  '@/mock': 'export const mockChatReply = () => "独立模拟回复";',
}

const entry = `
  import assert from 'node:assert/strict';
  import { webcrypto } from 'node:crypto';
  import { test } from 'node:test';
  import { createPinia, disposePinia, setActivePinia } from 'pinia';
  import { useChatStore } from '@/stores/useChatStore';
  import { requests } from '@/api/chat';
  import { edits, confirmations } from '@/api/interview';

  if (!globalThis.crypto) globalThis.crypto = webcrypto;

  function state(sessionId, version = 1, confirmed = false) {
    return {
      session_id: sessionId,
      status: confirmed ? 'confirmed' : 'in_progress',
      profile: { research_interests: ['自然语言处理'], interest_statement: '自然语言处理' },
      profile_version: version,
      current_question: null,
      needs_confirmation: false,
      recommend_ready: confirmed,
    };
  }
  function fixture() {
    const pinia = createPinia();
    setActivePinia(pinia);
    requests.length = 0;
    edits.length = 0;
    confirmations.length = 0;
    const chat = useChatStore();
    chat.initWelcome();
    return { chat, dispose: () => disposePinia(pinia) };
  }
  function contents(messages) { return messages.map((message) => message.content); }
  async function beginKnownSession(chat) {
    await chat.send('自然语言处理');
    const request = requests.at(-1);
    request.chunk('第一个问题');
    request.done(state(request.payload.session_id, 2));
    return request.payload.session_id;
  }

  await test('new conversation rejects late chunks, success, and failure without stopping its new request', async () => {
    const f = fixture();
    try {
      await f.chat.send('旧会话回答');
      const old = requests[0];
      f.chat.newConversation();
      await f.chat.send('新会话回答');
      const current = requests[1];
      const currentSession = f.chat.sessionId;
      assert.notEqual(currentSession, old.payload.session_id);
      assert.equal(old.controller.signal.aborted, true);
      old.chunk('旧内容');
      old.done(state(old.payload.session_id, 99, true));
      old.error({ response: { status: 422 } });
      assert.equal(f.chat.sessionId, currentSession);
      assert.equal(f.chat.profileVersion, null);
      assert.equal(f.chat.recommendReady, false);
      assert.equal(f.chat.streaming, true);
      assert.equal(f.chat.messages.at(-1).content, '');
      assert(!contents(f.chat.messages).some((content) => content.includes('旧')));
      current.chunk('新内容');
      current.done(state(currentSession, 2));
      assert.equal(f.chat.messages.at(-1).content, '新内容');
      assert.equal(f.chat.profileVersion, 2);
      assert.equal(f.chat.streaming, false);
    } finally { f.dispose(); }
  });

  await test('abort invalidates old callbacks both before and during a following send', async () => {
    const f = fixture();
    try {
      await f.chat.send('被中断回答');
      const old = requests[0];
      f.chat.abort();
      assert.equal(f.chat.streaming, false);
      old.chunk('不应追加');
      old.done(state('old-state', 88, true));
      old.error(new Error('late failure'));
      assert.equal(f.chat.profileVersion, null);
      assert.equal(f.chat.messages.at(-1).content, '');
      await f.chat.send('继续回答');
      old.error(new Error('late failure again'));
      old.done(state('old-state', 89, true));
      assert.equal(f.chat.streaming, true);
      assert.equal(f.chat.profileVersion, null);
      requests[1].done(state(requests[1].payload.session_id, 2));
      assert.equal(f.chat.streaming, false);
    } finally { f.dispose(); }
  });

  await test('422-rejected answer and local error text never enter the next request payload', async () => {
    const f = fixture();
    try {
      const sessionId = await beginKnownSession(f.chat);
      await f.chat.send('被服务端拒绝的长回答');
      requests[1].error({ response: { status: 422, data: { detail: '回答过长' } } });
      assert.equal(f.chat.streaming, false);
      assert.equal(f.chat.profileVersion, 2);
      assert.equal(f.chat.sessionId, sessionId);
      const rejected = f.chat.messages.find((message) => message.content === '被服务端拒绝的长回答');
      assert.equal(rejected.rejected, true);
      assert.equal(f.chat.messages.at(-1).localOnly, true);
      const localErrorText = f.chat.messages.at(-1).content;
      await f.chat.send('有效的新回答');
      const next = requests[2];
      const sent = contents(next.payload.messages);
      assert.equal(f.chat.streaming, true);
      assert.equal(next.payload.session_id, sessionId);
      assert(sent.includes('自然语言处理'));
      assert(sent.includes('有效的新回答'));
      assert(!sent.includes('被服务端拒绝的长回答'));
      assert(!sent.includes(localErrorText));
      next.done(state(sessionId, 3));
      assert.equal(f.chat.profileVersion, 3);
      assert.equal(f.chat.streaming, false);
    } finally { f.dispose(); }
  });

  await test('network failure keeps user history for persisted-turn recovery but omits local error narration', async () => {
    const f = fixture();
    try {
      const sessionId = await beginKnownSession(f.chat);
      await f.chat.send('可能已经写入服务端的回答');
      requests[1].error(new Error('connection reset after request'));
      const uncertain = f.chat.messages.find((message) => message.content === '可能已经写入服务端的回答');
      assert.notEqual(uncertain.rejected, true);
      assert.equal(f.chat.messages.at(-1).localOnly, true);
      const localErrorText = f.chat.messages.at(-1).content;
      assert.equal(f.chat.profileVersion, 2);
      await f.chat.send('下一轮有效回答');
      const next = requests[2];
      assert.deepEqual(
        next.payload.messages.filter((message) => message.role === 'user').map((message) => message.content),
        ['自然语言处理', '可能已经写入服务端的回答', '下一轮有效回答'],
      );
      assert(!contents(next.payload.messages).includes(localErrorText));
      next.done(state(sessionId, 4));
      assert.equal(f.chat.profileVersion, 4);
      assert.equal(f.chat.streaming, false);
    } finally { f.dispose(); }
  });

  await test('late previous failure cannot mark the current user answer rejected or replace confirmed state', async () => {
    const f = fixture();
    try {
      await f.chat.send('旧回答');
      const old = requests[0];
      f.chat.newConversation();
      await f.chat.send('已确认的新回答');
      requests[1].done(state(f.chat.sessionId, 7, true));
      old.error({ response: { status: 422 } });
      old.done(state('old-session', 99));
      assert.equal(f.chat.recommendReady, true);
      assert.equal(f.chat.interviewStatus, 'confirmed');
      assert.equal(f.chat.profileVersion, 7);
      const currentUser = f.chat.messages.find((message) => message.role === 'user');
      assert.notEqual(currentUser.rejected, true);
    } finally { f.dispose(); }
  });

  await test('profile-edit response cannot restore the previous conversation after reset', async () => {
    const f = fixture();
    try {
      const sessionId = await beginKnownSession(f.chat);
      const edit = f.chat.updateInterviewProfile({ research_mode: 'engineering' });
      assert.equal(edits.length, 1);
      f.chat.newConversation();
      edits[0].resolve(state(sessionId, 3));
      await edit;
      assert.equal(f.chat.sessionId, undefined);
      assert.equal(f.chat.profileVersion, null);
      assert.equal(f.chat.profile, null);
    } finally { f.dispose(); }
  });

  await test('confirmation response cannot restore the previous confirmed profile after reset', async () => {
    const f = fixture();
    try {
      const sessionId = await beginKnownSession(f.chat);
      const confirmation = f.chat.confirmInterviewProfile();
      assert.equal(confirmations.length, 1);
      f.chat.newConversation();
      confirmations[0].resolve(state(sessionId, 3, true));
      await confirmation;
      assert.equal(f.chat.sessionId, undefined);
      assert.equal(f.chat.profileVersion, null);
      assert.equal(f.chat.recommendReady, false);
      assert.equal(f.chat.interviewStatus, 'in_progress');
    } finally { f.dispose(); }
  });

  await test('current profile edits and confirmation still apply their returned versions', async () => {
    const f = fixture();
    try {
      const sessionId = await beginKnownSession(f.chat);
      const edit = f.chat.updateInterviewProfile({ research_mode: 'engineering' });
      assert.deepEqual(edits[0].args, [sessionId, 2, { research_mode: 'engineering' }]);
      const editedState = state(sessionId, 3);
      editedState.profile.research_mode = 'engineering';
      edits[0].resolve(editedState);
      assert.equal(await edit, true);
      assert.equal(f.chat.profileVersion, 3);
      assert.equal(f.chat.profile.research_mode, 'engineering');
      const confirmation = f.chat.confirmInterviewProfile();
      assert.deepEqual(confirmations[0].args, [sessionId, 3]);
      confirmations[0].resolve(state(sessionId, 4, true));
      assert.equal(await confirmation, true);
      assert.equal(f.chat.profileVersion, 4);
      assert.equal(f.chat.recommendReady, true);
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
      name: 'controlled-chat-http',
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
  const bundlePath = join(temporaryDirectory, 'chat-state-tests.mjs')
  await writeFile(bundlePath, result.outputFiles[0].text)
  await import(pathToFileURL(bundlePath).href)
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true })
}
