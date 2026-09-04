import { test } from 'node:test'
import assert from 'node:assert/strict'
import { loadTypescript } from './load-typescript.mjs'
const api = loadTypescript(new URL('../src/api.ts', import.meta.url))

test('once and session approval buttons send distinguishable authorization scopes', async context => {
  const payloads = []
  context.mock.method(globalThis, 'fetch', async (_url, init) => {
    payloads.push(JSON.parse(init.body))
    return Response.json({ok: true, reason:'approved'})
  })
  await api.approveRequest('approval-id', 'session-A', 'once')
  await api.approveRequest('approval-id', 'session-A', 'session')
  assert.deepEqual(payloads, [{session_id:'session-A', scope:'once'}, {session_id:'session-A', scope:'session'}])
})

test('HTTP 200 with a refused approval is surfaced as failure', async context => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ok:false, reason:'expired approval'}))
  await assert.rejects(api.approveRequest('expired', 'session-A', 'once'), /expired approval/)
})

test('document upload preserves raw bytes and encodes the filename in the session route', async context => {
  const file = new File(['document'], '测试 & note.pdf', {type:'application/pdf'})
  context.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(url, '/api/v1/sessions/A/attachments?filename=' + encodeURIComponent(file.name))
    assert.equal(init.body, file)
    assert.equal(init.headers['Content-Type'], 'application/pdf')
    return Response.json({id:'attachment-1', name:file.name})
  })
  assert.equal((await api.uploadAttachment('A', file)).id, 'attachment-1')
})

test('backup verification failure remains visible to the page', async context => {
  context.mock.method(globalThis, 'fetch', async () => new Response('invalid archive', {status:422}))
  await assert.rejects(api.verifyBackup('backup-id'), /422.*invalid archive/)
})
