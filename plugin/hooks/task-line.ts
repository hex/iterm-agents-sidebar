// ABOUTME: The task note a Claude session writes about its own work, for the Agents sidebar: the rules of begin and
// ABOUTME: report, the two tools' specs, and the parse of their untyped input. Pure: link.tsx reads and writes the file.
import type { ToolSpec } from 'claude-code'

export const TITLE_WIDTH = 80
export const ACTIVITY_WIDTH = 40

/** The note as both readers take it. `ts` is epoch seconds. `percent` null with `done` false is unknown or not yet reported. */
export type TaskNote = {
  task: string; title: string; activity: string | null; percent: number | null; done: boolean; ts: number
}

export type TaskToolKind = 'begin' | 'report'

/** What one call does: the note to write, or why nothing is written, in task.py's words. */
export type TaskCall = { kind: 'write'; note: TaskNote } | { kind: 'refused'; reason: string }

// Control characters and the bidi overrides that could make a label read as something else: task.py's _UNPRINTABLE.
const UNPRINTABLE = /[\x00-\x1f\x7f‪-‮⁦-⁩]/gu

/** Unprintables removed, cut to `width` code points (Python slices code points, not UTF-16 units), trimmed. */
export function clean(text: string, width: number): string {
  return [...text.replace(UNPRINTABLE, '')].slice(0, width).join('').trim()
}

/** The file's JSON as a note, or null when there is none or it is not one: task.py's read_note. */
export function parseNote(value: unknown): TaskNote | null {
  return typeof value === 'object' && value !== null && 'task' in value ? value as TaskNote : null
}

/** The decision for one tool call: the untyped input parsed at this boundary, then begin or report, with the checks in
 * task.py's order so the same bad input gets the same first refusal. `begin` ignores the current note: it starts over. */
export function taskCall(kind: TaskToolKind, input: Record<string, unknown>, current: TaskNote | null,
  nowSeconds: number, taskId: string): TaskCall {
  if (kind === 'begin') {
    const title = clean(typeof input.title === 'string' ? input.title : '', TITLE_WIDTH)
    if (!title) return { kind: 'refused', reason: 'title is empty' }
    return { kind: 'write', note: { task: taskId, title, activity: null, percent: null, done: false, ts: nowSeconds } }
  }
  if (!current) return { kind: 'refused', reason: 'no task yet: run begin first' }
  if (current.done) return { kind: 'refused', reason: 'task is done: begin a new one for more work' }
  const activity = clean(typeof input.activity === 'string' ? input.activity : '', ACTIVITY_WIDTH)
  if (!activity) return { kind: 'refused', reason: 'activity is empty' }
  const percent = input.percent
  if (percent !== null && !(Number.isInteger(percent) && (percent as number) >= 0 && (percent as number) <= 100)) {
    return { kind: 'refused', reason: 'percent must be 0 to 100' }
  }
  const done = percent === 100
  return { kind: 'write', note: { ...current, activity: done ? 'Complete' : activity, percent: percent as number | null, done, ts: nowSeconds } }
}

/** One line for the model after a write. */
export function summary(note: TaskNote): string {
  if (note.done) return `Task line: ${note.title} · Complete`
  if (note.activity === null) return `Task line: ${note.title}`
  return `Task line: ${note.title} · ${note.activity} · ${note.percent ?? '?'}%`
}

/** A task id unique within the session's note: the clock in base 36 and a per-process counter. No reader compares
 * ids across sessions; sidebar.py only checks the key is present. */
export function taskIdAt(clockMs: number, counter: number): string {
  return `${Math.floor(clockMs).toString(36)}${counter.toString(36).padStart(2, '0')}`
}

/** The two tools as registered. Descriptions carry the call contract only; the rules live in task-instructions.md. */
export const TASK_TOOLS: Record<TaskToolKind, ToolSpec> = {
  begin: {
    name: 'task_begin',
    description: "Starts a new task on this session's Agents sidebar card: the title of the user's current request. "
      + 'Replaces any task before it.',
    inputSchema: { type: 'object', required: ['title'], properties: {
      title: { type: 'string', description: 'A short title for the whole request, up to 80 characters.' } } },
  },
  report: {
    name: 'task_report',
    description: "Reports progress on the current task to this session's Agents sidebar card. 100 marks it Complete "
      + 'and locks it; more work needs task_begin.',
    inputSchema: { type: 'object', required: ['activity', 'percent'], properties: {
      activity: { type: 'string', description: 'Two to four words, such as "Reading code", up to 40 characters.' },
      percent: { type: ['integer', 'null'], minimum: 0, maximum: 100,
        description: 'Your estimate of the whole request in five-point steps, or null while the scope is unclear.' } } },
  },
}
