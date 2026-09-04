import { test } from 'node:test'
import assert from 'node:assert/strict'
import { loadTypescript } from './load-typescript.mjs'
const { formatUtcTimestamp } = loadTypescript(new URL('../src/time.ts', import.meta.url))

test('offset-free SQLite timestamps are interpreted as UTC before local display', () => {
  assert.equal(formatUtcTimestamp('2026-09-04T07:24:00'), new Date('2026-09-04T07:24:00Z').toLocaleString())
})

test('explicit timezone offsets are preserved', () => {
  assert.equal(formatUtcTimestamp('2026-09-04T15:24:00+08:00'), new Date('2026-09-04T07:24:00Z').toLocaleString())
  assert.equal(formatUtcTimestamp('invalid'), '未知时间')
})
