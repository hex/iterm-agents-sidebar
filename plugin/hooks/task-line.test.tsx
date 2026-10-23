// ABOUTME: Tests for the task line's pure rules: the shared cases task.py answers to as well, the summary line, and the
// ABOUTME: parse of untyped input. The tools' serving, files and marker are in task.test.tsx.
import { expect, test } from 'claude-code/testing'
import cases from './task-cases'
import { clean, parseNote, summary, taskCall, taskIdAt, type TaskNote } from './task-line'

type Step = { verb: 'begin'; title: string; now: number } | { verb: 'report'; activity: string; percent: number | null; now: number }
type Case = { name: string; steps: Step[]; expect?: Partial<TaskNote>; error?: string }

for (const c of cases as Case[]) {
  test(`shared case: ${c.name}`, () => {
    let note: TaskNote | null = null
    c.steps.forEach((step, i) => {
      const input = step.verb === 'begin' ? { title: step.title } : { activity: step.activity, percent: step.percent }
      const call = taskCall(step.verb, input, note, step.now, 'id')
      const last = i === c.steps.length - 1
      if (last && c.error !== undefined) expect(call).toEqual({ kind: 'refused', reason: c.error })
      else {
        expect(call.kind).toBe('write')
        if (call.kind === 'write') note = call.note
      }
    })
    if (c.expect) {
      const got = note as TaskNote | null
      expect(got).not.toBeNull()
      expect(Object.fromEntries(Object.keys(c.expect).map(key => [key, (got as any)[key]]))).toEqual(c.expect)
    }
  })
}

test('a percent that is a float or a numeric string is refused, as task.py refuses what argparse would not parse', () => {
  const note: TaskNote = { task: 'a', title: 'Fix', activity: null, percent: null, done: false, ts: 1 }
  for (const percent of [35.5, '35', true, undefined]) {
    expect(taskCall('report', { activity: 'Reading', percent }, note, 2, 'id')).toEqual({ kind: 'refused', reason: 'percent must be 0 to 100' })
  }
})

test('a title that is not a string is an empty title', () => {
  expect(taskCall('begin', { title: 7 }, null, 1, 'id')).toEqual({ kind: 'refused', reason: 'title is empty' })
  expect(taskCall('begin', {}, null, 1, 'id')).toEqual({ kind: 'refused', reason: 'title is empty' })
})

test('the summary names the title, then the activity and percent, a question mark for unknown, Complete when done', () => {
  const fresh: TaskNote = { task: 'a', title: 'Fix', activity: null, percent: null, done: false, ts: 1 }
  expect(summary(fresh)).toBe('Task line: Fix')
  expect(summary({ ...fresh, activity: 'Assessing', percent: null })).toBe('Task line: Fix · Assessing · ?%')
  expect(summary({ ...fresh, activity: 'Reading code', percent: 35 })).toBe('Task line: Fix · Reading code · 35%')
  expect(summary({ ...fresh, activity: 'Complete', percent: 100, done: true })).toBe('Task line: Fix · Complete')
})

test('parseNote takes an object with a task key and nothing else', () => {
  expect(parseNote({ task: 'a', title: 'x' })).toEqual({ task: 'a', title: 'x' })
  expect(parseNote({ title: 'x' })).toBeNull()
  expect(parseNote('nope')).toBeNull()
  expect(parseNote(null)).toBeNull()
})

test('clean counts code points and task ids are base-36 clock plus counter', () => {
  expect(clean('x'.repeat(79) + '😀tail', 80)).toBe('x'.repeat(79) + '😀')
  expect(taskIdAt(1_000_000, 1)).toBe('lfls01')
  expect(taskIdAt(1_000_000, 36)).toBe('lfls10')
})
