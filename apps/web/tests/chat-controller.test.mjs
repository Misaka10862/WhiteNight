import { test } from 'node:test'
import assert from 'node:assert/strict'
import { loadTypescript } from './load-typescript.mjs'
const { ChatController, shouldSendOnEnter } = loadTypescript(new URL('../src/chatController.ts', import.meta.url))

const flush = () => new Promise(resolve => setImmediate(resolve))
function fixture() {
  const sockets = [], refreshed = [], cancelled = []
  const controller = new ChatController({
    socket() {
      const socket = { onopen: null, onmessage: null, onerror: null, onclose: null,
        send(data) { this.payload = JSON.parse(data) }, close() { this.closed = true } }
      sockets.push(socket)
      return socket
    },
    requestId: () => `request-${sockets.length + 1}`,
    refresh: async id => { refreshed.push(id) },
    cancel: async id => { cancelled.push(id) },
  })
  const emit = (index, message) => sockets[index].onmessage?.({ data: JSON.stringify(message) })
  return { controller, sockets, refreshed, cancelled, emit }
}

test('streams are owned by session and persist without UI subscribers', async () => {
  const {controller, sockets, emit} = fixture()
  let changes = 0
  const unsubscribe = controller.subscribe(() => changes++)
  controller.start({sessionId:'A', text:'first'})
  sockets[0].onopen()
  const subscribedChanges = changes
  unsubscribe()
  emit(0, {type:'chunk', delta:'A only'})
  controller.start({sessionId:'B', text:'second'})
  emit(1, {type:'chunk', delta:'B only'})
  assert.equal(controller.snapshot('A').streamingText, 'A only')
  assert.equal(controller.snapshot('B').streamingText, 'B only')
  assert.equal(sockets[0].payload.request_id, 'request-1')
  assert.equal(changes, subscribedChanges)
})

test('an interrupted request refreshes only its history and does not resend', async () => {
  const {controller, sockets, refreshed} = fixture()
  controller.start({sessionId:'A', text:'first'})
  sockets[0].onclose()
  await flush()
  assert.equal(controller.snapshot('A').status, 'failed')
  assert.deepEqual(refreshed, ['A'])
  assert.equal(sockets.length, 1)
})

test('cancel calls the server request id, closes the socket and ignores late events', async () => {
  const {controller, sockets, cancelled} = fixture()
  controller.start({sessionId:'A', text:'first'})
  sockets[0].onopen()
  const lateEvent = sockets[0].onmessage
  await controller.cancel('A')
  assert.deepEqual(cancelled, ['request-1'])
  assert.equal(controller.snapshot('A').status, 'cancelled')
  lateEvent({data: JSON.stringify({type:'chunk', delta:'stale after cancel'})})
  assert.equal(controller.snapshot('A').status, 'cancelled')
  controller.start({sessionId:'A', text:'new request'})
  lateEvent({data: JSON.stringify({type:'chunk', delta:'stale'})})
  assert.equal(controller.snapshot('A').streamingText, '')
})

test('pending user text stays visible until completion refreshes persisted history', async () => {
  const {controller, emit, refreshed} = fixture()
  controller.start({sessionId:'A', text:'keep visible'})
  emit(0, {type:'start'})
  assert.equal(controller.snapshot('A').text, 'keep visible')
  emit(0, {type:'done'})
  await flush()
  assert.equal(controller.snapshot('A').status, 'completed')
  assert.deepEqual(refreshed, ['A'])
})

test('IME confirmation Enter and Shift+Enter do not send a message', () => {
  assert.equal(shouldSendOnEnter({key:'Enter', shiftKey:false, isComposing:true}), false)
  assert.equal(shouldSendOnEnter({key:'Enter', shiftKey:false, keyCode:229}), false)
  assert.equal(shouldSendOnEnter({key:'Enter', shiftKey:true}), false)
  assert.equal(shouldSendOnEnter({key:'Enter', shiftKey:false}), true)
})

test('a connection can be stopped before its request reaches the server', async () => {
  const {controller, sockets, cancelled} = fixture()
  controller.start({sessionId:'A', text:'not sent'})
  const lateOpen = sockets[0].onopen
  await controller.cancel('A')
  lateOpen()
  assert.equal(sockets[0].payload, undefined)
  assert.deepEqual(cancelled, [])
  assert.equal(controller.snapshot('A').status, 'cancelled')
})

test('a malformed JSON event closes the stream and refreshes its history', async () => {
  const {controller, sockets, refreshed} = fixture()
  controller.start({sessionId:'A', text:'first'})
  assert.doesNotThrow(() => sockets[0].onmessage({data:'null'}))
  await flush()
  assert.equal(controller.snapshot('A').status, 'failed')
  assert.deepEqual(refreshed, ['A'])
})
