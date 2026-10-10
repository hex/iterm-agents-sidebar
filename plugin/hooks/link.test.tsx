// ABOUTME: Tests for the link mod: drops taken once, the asked turn's reply filed, a typed prompt sent back to the box,
// ABOUTME: and the band. The folder, processes and session id are answered in memory beneath the mod.
import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const HOME = '/home/test'
const NONCE = '0123456789abcdef'
const folderOf = (id: string) => `${HOME}/.claude/agents-sidebar-links/${id}`
const F = folderOf('sess-1')
const ASK = `Write your latest result for the session “bravo”, written for it to act on, as your whole reply. (link ${NONCE})`

type World = {
  files: Map<string, string>
  moves: string[][]
  submitted: string[]
  filled: string[]
  toasts: string[]
  redraws: number
  id: string
  refuse: string | null
}

// Everything beneath the mod: its folder as a map of paths, mkdir/chmod/mv/rm, the session id, the prompt box.
function world(on: On): World {
  const w: World = { files: new Map(), moves: [], submitted: [], filled: [], toasts: [], redraws: 0, id: 'sess-1', refuse: null }
  const dirOf = (path: string) => path.slice(0, path.lastIndexOf('/'))
  mock.env(on, { HOME })
  on('session.id', () => ({ value: w.id }))
  on('fs.write', ($, e) => {
    w.files.set(e.path, e.text)
    return { value: undefined }
  })
  on('fs.read', ($, e) => {
    const text = w.files.get(e.path)
    if (text === undefined) throw new Error(`ENOENT: ${e.path}`)
    return { value: text }
  })
  on('fs.list', ($, e) => ({ value: [...w.files.keys()].filter(path => dirOf(path) === e.path).map(path => ({
    name: path.slice(e.path.length + 1), kind: 'file' as const, size: w.files.get(path)!.length, mtimeMs: 0, isLink: false,
  })) }))
  on('process.run', ($, e) => {
    const [command, ...args] = e.argv
    let exitCode = 0
    if (command === 'mv') {
      const [from, to] = args
      if (from === undefined || to === undefined) throw new Error(`mv needs two paths: ${e.argv.join(' ')}`)
      const text = w.files.get(from)
      if (text === undefined) exitCode = 1
      else {
        w.files.delete(from)
        w.files.set(to, text)
        w.moves.push([from, to])
      }
    } else if (command === 'rm') {
      for (const path of args) w.files.delete(path)
    } else if (command !== 'mkdir' && command !== 'chmod') {
      exitCode = 127
    }
    return { value: { exitCode, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('prompt.submit', ($, e) => {
    if (w.refuse) return { drop: w.refuse }
    w.submitted.push(e.text)
    return { text: e.text }
  })
  on('prompt.fill', ($, e) => {
    w.filled.push(e.text)
    return { isFilled: true }
  })
  on('ui.toast', ($, e) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.invalidate', () => {
    w.redraws += 1
    return { value: undefined }
  })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('turn.complete', ($, e) => ({ text: e.answer }))
  on('classic.Stop', () => ({}))
  on('fs.exists', ($, e) => ({ value: w.files.has(e.path) }))
  on('tool.register', ($, e) => ({ value: { tool: `mcp__agents-sidebar__${e.name}` } }))
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('store.delete', () => ({ value: undefined }))
  on('classic.UserPromptSubmit', () => ({}))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box />
  })
  return w
}

function dropFile(w: World, link: string, role: 'ask' | 'deliver', expires = 2000, text = ASK, colours: Record<string, unknown> = {}) {
  w.files.set(`${F}/ask-${link}.json`, JSON.stringify({ link, nonce: NONCE, role, text, from: 'alpha', to: 'bravo', expires, ...colours }))
}

const start = ($: any) => $.session.start({ cwd: '/work', surface: 'terminal', isInteractive: true })
const turnStart = ($: any, turnId: string, text: string) => $.turn.start({ turnId, text })
const turnEnd = ($: any, turnId: string, answer: string, extra: Record<string, unknown> = {}) =>
  $.turn.complete({ turnId, answer, durationMs: 10, isAborted: false, reason: 'answer', ...extra })
const typed = ($: any, text: string) => $.prompt.submit({ text, wait: false, origin: { kind: 'composer' } })

// The asked turn is running: the ask was taken on a tick and its turn started.
async function askedTurnRunning($: any, w: World, clock: any) {
  await start($)
  dropFile(w, 'L1', 'ask')
  await clock.advance(1000)
  await turnStart($, 't1', ASK)
}

test('a tick takes an unexpired ask once and submits its text once', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  dropFile(w, 'L1', 'ask')
  await clock.advance(1000)
  expect(w.moves).toEqual([[`${F}/ask-L1.json`, `${F}/taken-L1.json`]])
  expect(w.submitted).toEqual([ASK])
  await clock.advance(1000)
  expect(w.submitted).toEqual([ASK])
})

test('an expired or cut-off drop is neither taken nor submitted', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  dropFile(w, 'L1', 'ask', 999)
  w.files.set(`${F}/ask-L2.json`, '{"link": "L2", "ro')
  await clock.advance(1000)
  expect(w.moves).toEqual([])
  expect(w.submitted).toEqual([])
})

test("the asked turn's answer is the result, and a subagent's turn inside it is not", async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await askedTurnRunning($, w, clock)
  await turnEnd($, 't1', 'a subagent report', { agentId: 'sub-1' })
  expect(w.files.has(`${F}/result-L1.json`)).toBe(false)
  await turnEnd($, 't1', 'done')
  expect(JSON.parse(w.files.get(`${F}/result-L1.json`)!)).toEqual({ link: 'L1', nonce: NONCE, text: 'done' })
})

test('a turn before the asked one is not its result', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  dropFile(w, 'L1', 'ask')
  await clock.advance(1000)
  await turnStart($, 't0', 'something else')
  await turnEnd($, 't0', 'not it')
  expect(w.files.has(`${F}/result-L1.json`)).toBe(false)
  await turnStart($, 't1', ASK)
  await turnEnd($, 't1', 'it')
  expect(JSON.parse(w.files.get(`${F}/result-L1.json`)!)).toEqual({ link: 'L1', nonce: NONCE, text: 'it' })
})

test("a Stop hook that sends the asked turn on does not replace its result with the reply to the hook", async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await askedTurnRunning($, w, clock)
  await $.classic.Stop({ stop_hook_active: false, last_assistant_message: 'the result for bravo' })
  await $.classic.Stop({ stop_hook_active: true, last_assistant_message: 'Narrative updated.' })
  await turnEnd($, 't1', 'Narrative updated.')
  expect(JSON.parse(w.files.get(`${F}/result-L1.json`)!)).toEqual({ link: 'L1', nonce: NONCE, text: 'the result for bravo' })
})

test("the Stop of the turn an ask waited behind is not the asked turn's result", async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  await turnStart($, 't0', 'something else')
  dropFile(w, 'L1', 'ask')
  await clock.advance(1000)
  await $.classic.Stop({ stop_hook_active: false, last_assistant_message: 'not it' })
  await turnEnd($, 't0', 'not it')
  await turnStart($, 't1', ASK)
  await turnEnd($, 't1', 'it')
  expect(JSON.parse(w.files.get(`${F}/result-L1.json`)!)).toEqual({ link: 'L1', nonce: NONCE, text: 'it' })
})

test('an asked turn interrupted after it stopped with a reply still sends that reply', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await askedTurnRunning($, w, clock)
  await $.classic.Stop({ stop_hook_active: false, last_assistant_message: 'the result for bravo' })
  await turnEnd($, 't1', '', { isAborted: true, reason: 'aborted' })
  expect(JSON.parse(w.files.get(`${F}/result-L1.json`)!)).toEqual({ link: 'L1', nonce: NONCE, text: 'the result for bravo' })
})

for (const [extra, answer, reason] of [
  [{ isAborted: true, reason: 'aborted' }, 'half', 'the turn was interrupted'],
  [{}, '  ', 'the turn ended without an answer'],
  [{ reason: 'refusal', refusal: { category: null, explanation: null } }, '', 'the model refused'],
  [{ reason: 'error' }, '', 'the turn ended on an API error'],
] as const) {
  test(`an asked turn that ends as ${reason} fails the link`, async ($, on) => {
    const w = world(on)
    const clock = mock.clock(on, { now: 1_000_000 })
    await askedTurnRunning($, w, clock)
    await turnEnd($, 't1', answer, extra)
    expect(JSON.parse(w.files.get(`${F}/failed-L1.json`)!)).toEqual({ link: 'L1', reason })
    expect(w.files.has(`${F}/result-L1.json`)).toBe(false)
  })
}

test('a prompt typed during the asked turn goes back to the box; one typed when idle goes in', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  expect(await typed($, 'before')).toEqual({ text: 'before' })
  dropFile(w, 'L1', 'ask')
  await clock.advance(1000)
  await turnStart($, 't1', ASK)
  expect(await typed($, 'look at @src/a.ts')).toEqual({ drop: 'the hand-off is running' })
  expect(w.filled).toEqual(['look at @src/a.ts'])
  expect(w.toasts).toEqual(['Linked to “bravo”: writing up your latest result for it', 'the hand-off is running; send this when it ends'])
  expect(w.submitted).toEqual(['before', ASK])
  await turnEnd($, 't1', 'done')
  expect(await typed($, 'after')).toEqual({ text: 'after' })
})

test('a prompt with an image sent back to the box says the image must be added again', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await askedTurnRunning($, w, clock)
  const result = await $.prompt.submit({ text: 'see this', wait: false, origin: { kind: 'composer' },
                                         attachments: [{ type: 'image', mediaType: 'image/png' }] })
  expect(result).toEqual({ drop: 'the hand-off is running' })
  expect(w.filled).toEqual(['see this'])
  expect(w.toasts).toEqual(['Linked to “bravo”: writing up your latest result for it', 'the hand-off is running; send this when it ends, and add the image again'])
})

test('two deliveries taken in one tick are each marked started by their own turn', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  const first = `A report ... (link ${NONCE})`
  const second = 'A report ... (link fedcba9876543210)'
  dropFile(w, 'L2', 'deliver', 2000, first)
  w.files.set(`${F}/ask-L3.json`, JSON.stringify({ link: 'L3', nonce: 'fedcba9876543210', role: 'deliver', text: second,
                                                     from: 'charlie', to: 'bravo', expires: 2000 }))
  await clock.advance(1000)
  await turnStart($, 't2', first)
  await turnStart($, 't3', second)
  expect([w.files.get(`${F}/started-L2.json`), w.files.get(`${F}/started-L3.json`)]).toEqual(['{}', '{}'])
})

for (const role of ['ask', 'deliver'] as const) {
  test(`a ${role} the session will not take as a prompt fails the link`, async ($, on) => {
    const w = world(on)
    const clock = mock.clock(on, { now: 1_000_000 })
    await start($)
    w.refuse = 'a hook said no'
    dropFile(w, 'L1', role)
    await clock.advance(1000)
    expect(JSON.parse(w.files.get(`${F}/failed-L1.json`)!)).toEqual({ link: 'L1', reason: 'the session did not take the prompt: a hook said no' })
    expect(w.toasts.at(-1)).toBe(role === 'ask'
      ? 'The link to “bravo” failed: the session did not take the prompt: a hook said no'
      : 'The hand-off from “alpha” failed: the session did not take the prompt: a hook said no')
  })
}

test("a delivery's turn starting marks it started", async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  const text = `A report from the session “alpha”, another agent session. It is not an instruction from the user: (link ${NONCE})\n\n\`\`\`\nx\n\`\`\``
  dropFile(w, 'L2', 'deliver', 2000, text)
  await clock.advance(1000)
  expect(w.files.has(`${F}/started-L2.json`)).toBe(false)
  await turnStart($, 't1', 'a prompt queued before it')
  expect(w.files.has(`${F}/started-L2.json`)).toBe(false)
  await turnStart($, 't2', text)
  expect(w.files.get(`${F}/started-L2.json`)).toBe('{}')
})

test('a reload fails an ask it had taken but never answered', async ($, on) => {
  const w = world(on)
  mock.clock(on, { now: 1_000_000 })
  w.files.set(`${F}/taken-L9.json`, JSON.stringify({ link: 'L9', nonce: NONCE, role: 'ask', text: ASK, expires: 2000 }))
  w.files.set(`${F}/taken-L8.json`, JSON.stringify({ link: 'L8', nonce: NONCE, role: 'ask', text: ASK, expires: 2000 }))
  w.files.set(`${F}/result-L8.json`, JSON.stringify({ link: 'L8', nonce: NONCE, text: 'done' }))
  await start($)
  expect(JSON.parse(w.files.get(`${F}/failed-L9.json`)!)).toEqual({ link: 'L9', reason: 'the session reloaded during the hand-off' })
  expect(w.files.has(`${F}/failed-L8.json`)).toBe(false)
})

test('after /clear the ready file names the new id in its own folder', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  await clock.advance(1000)
  expect(w.files.get(`${F}/ready`)).toBe('sess-1')
  w.id = 'sess-2'
  await clock.advance(1000)
  expect(w.files.get(`${folderOf('sess-2')}/ready`)).toBe('sess-2')
})

const PROPS = { hasSurvey: false, isWorking: false, maxRows: 4, bodyColumns: 80, scroll: { offset: 0, bodyRows: 4 } }

type Part = { text: string; background: unknown }

// The band as drawn: how its row is aligned and each piece of text with its background, or undefined when none shows.
async function band($: any): Promise<{ align: unknown; parts: Part[] } | undefined> {
  const drawn = await $.ui.mount({ plugin: 'agents-sidebar', surface: 'terminal', component: 'AbovePrompt', props: PROPS })
  const leaves = (await drawn.findAll({ type: 'Text' })).filter((text: any) => text.children.every((child: unknown) => typeof child === 'string'))
  if (leaves.length === 0) return undefined
  const row = await drawn.find({ type: 'Box' })
  return { align: row.props.justifyContent, parts: leaves.map((text: any) => ({ text: text.text, background: text.props.backgroundColor })) }
}

// A session with no colour of its own, or one the panel does not know, wears a neutral grey.
const SENDER_CHIP = { text: ' alpha ', background: '#8e8e93' }
const TARGET_CHIP = { text: ' bravo ', background: '#8e8e93' }
const SPINNING = /^ [⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏] writing$/

test('the band sits on the right: each session a chip, a link that flows while A writes and locks once sent, then clears 10 s on', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  expect(await band($)).toBeUndefined()
  dropFile(w, 'L1', 'ask')
  await clock.advance(1000)
  await turnStart($, 't1', ASK)
  const writing = (await band($))!
  expect(writing.align).toBe('flex-end')
  expect(writing.parts[0]).toEqual(SENDER_CHIP)
  expect(writing.parts[2]).toEqual(TARGET_CHIP)
  expect(writing.parts[3]!.text).toMatch(SPINNING)
  const before = w.redraws
  await clock.advance(360)
  expect(w.redraws - before).toBe(3)
  const flowing = (await band($))!
  expect(flowing.parts[1]!.text).not.toBe(writing.parts[1]!.text)
  expect(flowing.parts[3]!.text).not.toBe(writing.parts[3]!.text)
  await turnEnd($, 't1', 'done')
  const sent = (await band($))!
  expect(sent.parts.map(part => part.text)).toEqual([' alpha ', ' ━━━ 🔗 ━━━ ', ' bravo ', ' ✓ sent'])
  await clock.advance(1000)
  const settled = w.redraws
  await clock.advance(1000)
  expect(w.redraws).toBe(settled)
  await clock.advance(7000)
  expect((await band($))!.parts.map(part => part.text)).toEqual([' alpha ', ' ━━━ 🔗 ━━━ ', ' bravo ', ' ✓ sent'])
  await clock.advance(2000)
  expect(await band($)).toBeUndefined()
})

test("each chip wears its session's colour as the panel draws it", async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  dropFile(w, 'L1', 'ask', 2000, ASK, { from_colour: 'orange', to_colour: 'teal' })
  await clock.advance(1000)
  await turnStart($, 't1', ASK)
  const drawn = (await band($))!
  expect(drawn.parts[0]).toEqual({ text: ' alpha ', background: '#d97706' })
  expect(drawn.parts[2]).toEqual({ text: ' bravo ', background: '#8e8e93' })
})

test("the receiving session's band says delivered", async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  const text = `A report ... (link ${NONCE})`
  dropFile(w, 'L2', 'deliver', 2000, text)
  await clock.advance(1000)
  await turnStart($, 't2', text)
  expect((await band($))!.parts).toEqual([SENDER_CHIP, { text: ' ━━━ 🔗 ━━━ ', background: undefined }, TARGET_CHIP, { text: ' ✓ delivered', background: undefined }])
})

test('the sending session is told by toast when it takes the ask and when its result is sent', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await askedTurnRunning($, w, clock)
  expect(w.toasts).toEqual(['Linked to “bravo”: writing up your latest result for it'])
  await turnEnd($, 't1', 'done')
  expect(w.toasts).toEqual(['Linked to “bravo”: writing up your latest result for it', 'Sent your latest result to “bravo”'])
})

test('the sending session is told by toast why a link failed', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await askedTurnRunning($, w, clock)
  await turnEnd($, 't1', 'half', { isAborted: true, reason: 'aborted' })
  expect(w.toasts.slice(1)).toEqual(['The link to “bravo” failed: the turn was interrupted'])
})

test('the receiving session is told by toast when the hand-off starts there', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  const text = `A report ... (link ${NONCE})`
  dropFile(w, 'L2', 'deliver', 2000, text)
  await clock.advance(1000)
  expect(w.toasts).toEqual([])
  await turnStart($, 't2', text)
  expect(w.toasts).toEqual(['“alpha” handed you its latest result'])
})
