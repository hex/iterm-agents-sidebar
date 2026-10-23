// ABOUTME: Tests for the task line's two tools as the link mod serves them: the note on disk, refusals as results, a
// ABOUTME: subagent turned away, concurrent reports in order, the marker emit-state.py reads, and a refused registration.
import { expect, mock, test } from 'claude-code/testing'
import { F, HOME, folderOf, world, type World } from './test-world'

const BEGIN = 'mcp__agents-sidebar__task_begin'
const REPORT = 'mcp__agents-sidebar__task_report'
const NOTE = `${HOME}/.claude/agents-sidebar-tasks/sess-1.json`

const start = ($: any) => $.session.start({ cwd: '/work', surface: 'terminal', isInteractive: true })
const begin = ($: any, title: unknown) => $.tool.call({ tool: BEGIN, title })
const report = ($: any, activity: unknown, percent: unknown, extra: Record<string, unknown> = {}) =>
  $.tool.call({ tool: REPORT, activity, percent, ...extra })
const note = (w: World, path = NOTE) => JSON.parse(w.files.get(path)!)
const staged = (w: World) => [...w.files.keys()].filter(p => p.includes('/.sess-1.json'))

test('begin writes the note whole, with the clock in seconds, and reports update it in place', async ($, on) => {
  const w = world(on)
  mock.clock(on, { now: 1_000_000 })
  await start($)
  expect((await begin($, 'Fix the login bug')).result).toBe('Task line: Fix the login bug')
  expect(note(w)).toEqual({ task: note(w).task, title: 'Fix the login bug', activity: null, percent: null, done: false, ts: 1000 })
  expect(typeof note(w).task).toBe('string')
  expect((await report($, 'Reading code', 35)).result).toBe('Task line: Fix the login bug · Reading code · 35%')
  expect(note(w)).toMatchObject({ title: 'Fix the login bug', activity: 'Reading code', percent: 35, done: false })
  expect((await report($, 'Assessing', null)).result).toBe('Task line: Fix the login bug · Assessing · ?%')
  expect(note(w).percent).toBeNull()
  expect(staged(w)).toEqual([])
  expect(w.runs.some(run => run[0] === 'python3')).toBe(false)
})

test('a hundred locks the task, and every refusal is a result the model reads, never a thrown error', async ($, on) => {
  const w = world(on)
  mock.clock(on, { now: 1_000_000 })
  await start($)
  expect((await report($, 'Reading', 5)).result).toBe('Not recorded: no task yet: run begin first')
  await begin($, 'Fix')
  expect((await report($, 'Done', 100)).result).toBe('Task line: Fix · Complete')
  expect(note(w)).toMatchObject({ activity: 'Complete', percent: 100, done: true })
  expect((await report($, 'More', 40)).result).toBe('Not recorded: task is done: begin a new one for more work')
  expect(note(w).done).toBe(true)
  expect((await begin($, '   ')).result).toBe('Not recorded: title is empty')
  expect((await begin($, 'Two')).result).toBe('Task line: Two')
  expect((await report($, 'Reading', 101)).result).toBe('Not recorded: percent must be 0 to 100')
  expect((await report($, '', 10)).result).toBe('Not recorded: activity is empty')
})

test('a subagent is turned away and nothing is written', async ($, on) => {
  const w = world(on)
  mock.clock(on, { now: 1_000_000 })
  await start($)
  expect((await begin($, 'Fix')).result).toBe('Task line: Fix')
  const before = w.files.get(NOTE)
  expect((await report($, 'Reading', 5, { agentId: 'agent-7' })).result)
    .toBe('Not recorded: only the main conversation reports the task line, not a subagent.')
  expect(w.files.get(NOTE)).toBe(before)
})

test('two reports in one message both land, in order', async ($, on) => {
  const w = world(on)
  mock.clock(on, { now: 1_000_000 })
  await start($)
  await begin($, 'Fix')
  const [first, second] = await Promise.all([report($, 'First', 10), report($, 'Second', 20)])
  expect(first.result).toBe('Task line: Fix · First · 10%')
  expect(second.result).toBe('Task line: Fix · Second · 20%')
  expect(note(w)).toMatchObject({ activity: 'Second', percent: 20 })
})

test('the note follows the session id of the moment, so a report after /clear files under the new id', async ($, on) => {
  const w = world(on)
  mock.clock(on, { now: 1_000_000 })
  await start($)
  await begin($, 'Fix')
  w.id = 'sess-2'
  expect((await report($, 'Reading', 5)).result).toBe('Not recorded: no task yet: run begin first')
  expect((await begin($, 'Again')).result).toBe('Task line: Again')
  expect(note(w, `${HOME}/.claude/agents-sidebar-tasks/sess-2.json`).title).toBe('Again')
  expect(note(w).title).toBe('Fix')
})

test('the marker names both tools for the session, on the tick and at every turn start', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  await clock.advance(1000)
  expect(JSON.parse(w.files.get(`${F}/task-tools.json`)!)).toEqual({ session: 'sess-1', begin: BEGIN, report: REPORT })
  w.id = 'sess-2'
  await $.turn.start({ turnId: 't1', text: 'hi' })
  expect(JSON.parse(w.files.get(`${folderOf('sess-2')}/task-tools.json`)!)).toEqual({ session: 'sess-2', begin: BEGIN, report: REPORT })
})

test('a refused registration leaves a marker that says so, and the partner tools still register', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  w.refuses = name => name.startsWith('task_') ? 'allowedMcpServers (managed): plugins outside policy may not add tools' : null
  await start($)
  await clock.advance(1000)
  expect(JSON.parse(w.files.get(`${F}/task-tools.json`)!)).toEqual({
    session: 'sess-1', refused: JSON.parse(w.files.get(`${F}/task-tools.json`)!).refused })
  expect(JSON.parse(w.files.get(`${F}/task-tools.json`)!).refused).toContain('allowedMcpServers')
  expect((await $.tool.call({ tool: 'mcp__agents-sidebar__partner_read' })).result).toBe('This session is not linked to another.')
})
