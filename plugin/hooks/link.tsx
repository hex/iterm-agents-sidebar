// ABOUTME: Linked cards and partner sessions, inside a Claude session: link drops and partner tasks taken from the
// ABOUTME: session's own folder, the two partner tools, replies filed, and the band above the prompt. One module per plugin.
import type { EngineInterface, PromptSubmitInput, Register, Timer, TurnCompleteInput, TurnStartInput } from 'claude-code'
import { TURNS_MAX, TAIL_BYTES, firstWords, readText } from './partner-text'

const TICK_MS = 1000
const CLEAR_MS = 10_000
// The band's animation: one frame of the flowing link and the spinner, and how long a new state stays bold.
const FRAME_MS = 120
const FLASH_MS = 600
const SPINNER = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
const FLOW = ['· ·', ' · ']
// The panel's session colours (SESSION_COLOURS in page.html), by the name a card wears; a card with none is grey.
const SESSION_HUE: Record<string, string> = {
  red: '#d64545', orange: '#d97706', yellow: '#ca9a04', green: '#3f9142',
  cyan: '#0e9494', blue: '#3b74d6', purple: '#8250c4', pink: '#c4508f',
}
const NO_HUE = '#8e8e93'
const hueOf = (colour: unknown): string => (typeof colour === 'string' && Object.hasOwn(SESSION_HUE, colour) ? SESSION_HUE[colour]! : NO_HUE)
const STATE_HUE: Record<Band['state'], string> = { writing: '#d97757', sent: '#4a8fd6', delivered: '#3fa66b' }
const SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9_-]*$/

type Drop = {
  link: string; nonce: string; role: 'ask' | 'deliver'; text: string; from: string; to: string; expires: number
  from_colour?: unknown; to_colour?: unknown
}
type Band = { from: string; to: string; fromHue: string; toHue: string; state: 'writing' | 'sent' | 'delivered'; since: number; until: number | null }

let folder: string | null = null
let home: string | null = null
// The asked turn, and its reply at its first Stop: a Stop hook that blocks sends the turn on, and the turn's
// final answer is then the reply to that hook, not the result.
let asked: { link: string; nonce: string; to: string; turnId: string | null; stopped: string | null } | null = null
// Deliveries waiting for their turn, by nonce: several senders can hand this session work at once.
const delivering = new Map<string, { link: string; from: string; to: string; fromHue: string; toHue: string }>()
let running: string | null = null
let band: Band | null = null
// Remote Control the daemon asked this session to turn back on after an account switch: taken once, run when idle.
// `taken` is where the job's file sits, so a /clear mid-job still removes it from the folder it was taken in.
let remote: { switchAt: number; expires: number; running: boolean; taken: string } | null = null
// Redraws the band each frame while it moves: the link flows and the spinner turns while A writes, and a new state is bold for a beat.
let frames: Timer | null = null

function animate($: EngineInterface): void {
  if (frames) return
  frames = $.clock.every(FRAME_MS, () => {
    void (async () => {
      const now = await $.clock.now()
      const moving = band !== null && (band.state === 'writing' || now - band.since < FLASH_MS)
      $.ui.invalidate('ui.render')
      if (!moving && frames) {
        frames.cancel()
        frames = null
      }
    })()
  })
}

// Why an asked turn that ended without an answer failed, by turn.complete's reason.
const FAILED: Record<string, string> = {
  aborted: 'the turn was interrupted',
  refusal: 'the model refused',
  error: 'the turn ended on an API error',
}

async function succeeded($: EngineInterface, argv: string[]): Promise<boolean> {
  return (await $.process.run(argv)).exitCode === 0
}

// The session's own folder; the id changes on /clear and on a resume, with no new session.start.
async function folderFor($: EngineInterface): Promise<string | null> {
  home = (await $.env.get('HOME')) ?? null
  const id = await $.session.id()
  if (!home || !SESSION_ID.test(id)) return null
  const path = `${home}/.claude/agents-sidebar-links/${id}`
  if (path !== folder) {
    if (!(await succeeded($, ['mkdir', '-m', '700', '-p', path]))) return null
    folder = path
  }
  return path
}

// Written to a dot-file, made 0600, then renamed, so the daemon never reads half a file.
async function writeWhole($: EngineInterface, name: string, value: unknown): Promise<void> {
  if (!folder) return
  const staged = `${folder}/.${name}`
  await $.fs.write(staged, JSON.stringify(value))
  if (await succeeded($, ['chmod', '600', staged])) await succeeded($, ['mv', staged, `${folder}/${name}`])
}

// A file's JSON, or null when it is missing or not yet whole. Typed any as JSON.parse is: every caller checks
// the shape it needs before it trusts a field.
async function readJson($: EngineInterface, path: string): Promise<any> {
  try {
    return JSON.parse(await $.fs.read(path))
  } catch {
    return null
  }
}

async function readDrop($: EngineInterface, path: string): Promise<Drop | null> {
  const drop = await readJson($, path)
  const whole = drop && typeof drop.text === 'string' && typeof drop.link === 'string' && typeof drop.nonce === 'string'
  return whole ? drop : null
}

// This session's state file under ~/.claude/sessions, found by its session id, which /clear changes in the same file.
async function ownState($: EngineInterface): Promise<any> {
  const dir = `${home}/.claude/sessions`
  const id = await $.session.id()
  for (const entry of await $.fs.list(dir)) {
    if (!entry.name.endsWith('.json')) continue
    const state = await readJson($, `${dir}/${entry.name}`)
    if (state && state.sessionId === id) return state
  }
  return null
}

async function remoteDone($: EngineInterface, outcome: string, reason: string): Promise<void> {
  const job = remote
  remote = null
  if (!job) return
  // The conversation's folder now, which a /clear while the command ran has moved on from: the panel reads it there.
  await folderFor($)
  await writeWhole($, 'remote-control-result.json', { switch_at: job.switchAt, outcome, reason })
  await succeeded($, ['rm', '-f', job.taken])
}

// Turns Remote Control back on when the daemon asks: never while a turn runs or a prompt waits, never when it is
// already on (the command would open its menu instead), and never twice for one ask.
async function keepRemote($: EngineInterface, path: string, now: number): Promise<void> {
  if (!remote) {
    // A job this session took before a reload is its own, still to finish; past its expiry it fails below.
    const taken = `${path}/remote-control-taken.json`
    const held = await readJson($, taken)
    if (held && typeof held.switch_at === 'number' && typeof held.expires === 'number') {
      remote = { switchAt: held.switch_at, expires: held.expires, running: false, taken }
    } else {
      const file = `${path}/remote-control.json`
      const asked = await readJson($, file)
      if (!asked || typeof asked.switch_at !== 'number' || typeof asked.expires !== 'number') return
      if (!(asked.expires * 1000 >= now)) {
        await succeeded($, ['rm', '-f', file])
        return
      }
      if (!(await succeeded($, ['mv', file, taken]))) return
      remote = { switchAt: asked.switch_at, expires: asked.expires, running: false, taken }
    }
  }
  // Claimed before the first await: ticks are not serialized, and one that slips past here while another reads the
  // state file would run the command twice, which opens Remote Control's menu.
  if (remote.running) return
  remote.running = true
  // No state file naming this session yet is waited out like a busy one: a read can land mid-rewrite, and for a
  // moment after /clear the file still names the old id.
  const state = await ownState($)
  if (!state || state.status !== 'idle') {
    if (now > remote.expires * 1000) return remoteDone($, 'failed', state ? 'the session did not go idle' : 'no session state file')
    remote.running = false
    return
  }
  if (typeof state.bridgeSessionId === 'string' && state.bridgeSessionId) return remoteDone($, 'already-on', '')
  try {
    await $.command.run({ command: 'remote-control' })
  } catch (error) {
    return remoteDone($, 'failed', String(error))
  }
  await remoteDone($, 'done', '')
}

async function tick($: EngineInterface): Promise<void> {
  const path = await folderFor($)
  if (!path) return
  await $.fs.write(`${path}/ready`, await $.session.id())
  const now = await $.clock.now()
  if (band && band.until !== null && now >= band.until) {
    band = null
    $.ui.invalidate('ui.render')
  }
  for (const entry of await $.fs.list(path)) {
    if (!entry.name.startsWith('ask-') || !entry.name.endsWith('.json')) continue
    const drop = await readDrop($, `${path}/${entry.name}`)
    if (!drop || !(drop.expires * 1000 >= now)) continue
    if (!(await succeeded($, ['mv', `${path}/${entry.name}`, `${path}/taken-${drop.link}.json`]))) continue
    if (drop.role === 'ask') {
      asked = { link: drop.link, nonce: drop.nonce, to: drop.to, turnId: null, stopped: null }
      band = { from: drop.from, to: drop.to, fromHue: hueOf(drop.from_colour), toHue: hueOf(drop.to_colour), state: 'writing', since: now, until: null }
      animate($)
      $.ui.toast(`Linked to “${drop.to}”: writing up your latest result for it`)
    } else {
      delivering.set(drop.nonce, { link: drop.link, from: drop.from, to: drop.to, fromHue: hueOf(drop.from_colour), toHue: hueOf(drop.to_colour) })
    }
    $.ui.invalidate('ui.render')
    void submitDrop($, drop)
  }
  // After the link drops, so a remote-control job that fails outright never holds up a hand-off; its failure is
  // filed for the panel to show.
  try {
    await keepRemote($, path, now)
  } catch (error) {
    await remoteDone($, 'failed', String(error))
  }
}

// A prompt the session will not take (a hook drops it, or the submit fails) fails its link at once,
// rather than leaving a taken drop that nothing will ever answer.
async function submitDrop($: EngineInterface, drop: Drop): Promise<void> {
  let refused: string | null = null
  try {
    const entered = await $.prompt.submit({ text: drop.text })
    if (entered.drop !== undefined) refused = `the session did not take the prompt: ${entered.drop}`
  } catch (error) {
    refused = `the session did not take the prompt: ${String(error)}`
  }
  if (refused === null) return
  if (drop.role === 'ask' && asked?.link === drop.link) {
    asked = null
    band = null
  }
  delivering.delete(drop.nonce)
  await writeWhole($, `failed-${drop.link}.json`, { link: drop.link, reason: refused })
  $.ui.toast(drop.role === 'ask' ? `The link to “${drop.to}” failed: ${refused}` : `The hand-off from “${drop.from}” failed: ${refused}`)
  $.ui.invalidate('ui.render')
}

// A reload forgets the asked turn, so an ask taken before it can never be answered: say so.
async function failTakenAsks($: EngineInterface): Promise<void> {
  const path = await folderFor($)
  if (!path) return
  const names = new Set<string>((await $.fs.list(path)).map(entry => entry.name))
  for (const name of names) {
    if (!name.startsWith('taken-') || !name.endsWith('.json')) continue
    const link = name.slice('taken-'.length, -'.json'.length)
    if (names.has(`result-${link}.json`) || names.has(`failed-${link}.json`)) continue
    const drop = await readDrop($, `${path}/${name}`)
    if (drop?.role === 'ask') await writeWhole($, `failed-${link}.json`, { link, reason: 'the session reloaded during the hand-off' })
  }
}

// Partner sessions: the panel's partner.json says who this session is linked with; the two tools read the partner's
// conversation and hand it tasks. The engine takes one hooks module per plugin and one hook per event, so the
// partner's part of each event runs inside the same hook as the link's.

const NOT_LINKED = 'This session is not linked to another.'
const LINKING_OFF = 'Linking is off in the agents sidebar: turn on Link cards under Experimental in its settings.'
const FROM_SUBAGENT = 'Only the main conversation can use the partner tools, not a subagent.'
const DECLINED = 'The user declined.'

type Partner = {
  id: string; me: string; label: string; transcript: string | null; profile: string; key: string; introduction: string
  state_note: string | null
}

let partner: Partner | null = null
// The permission mode of the latest prompt; until a prompt is seen the tools ask.
let mode: string | null = null
const tools = { read: '', delegate: '' }
// The crossing the band shows: a task out from this session or in from its partner, then its answer for 10 s.
let crossing: { from: string; to: string; state: 'asked' | 'answered'; until: number | null } | null = null

async function crossed($: EngineInterface, from: string, to: string, state: 'asked' | 'answered'): Promise<void> {
  crossing = { from, to, state, until: state === 'answered' ? (await $.clock.now()) + CLEAR_MS : null }
  $.ui.invalidate('ui.render')
}

// Whether the panel's settings have linking on; it is experimental and starts off, so a file not read is off.
async function linkingOn($: EngineInterface): Promise<boolean> {
  const base = await $.env.get('HOME')
  return !!base && (await readJson($, `${base}/.claude/agents-sidebar-settings.json`))?.links === true
}

// The daemon's partner.json, or null when this session is not linked or the file is not whole.
async function readPartner($: EngineInterface, path: string): Promise<Partner | null> {
  const value = await readJson($, path)
  const whole = value && typeof value.id === 'string' && typeof value.me === 'string' && typeof value.label === 'string'
    && typeof value.profile === 'string' && typeof value.key === 'string' && typeof value.introduction === 'string'
    && (value.transcript === null || typeof value.transcript === 'string')
    && (value.state_note === null || typeof value.state_note === 'string')
  return whole ? value : null
}

async function partnerTick($: EngineInterface): Promise<void> {
  const path = await folderFor($)
  if (!path) return
  partner = (await $.fs.exists(`${path}/partner.json`)) ? await readPartner($, `${path}/partner.json`) : null
  if (crossing?.until != null && (await $.clock.now()) >= crossing.until) {
    crossing = null
    $.ui.invalidate('ui.render')
  }
  await deliverLateAnswers($, path)
  await takeTasks($, path)
}

// Outside bypass mode each call asks you first; a dismissed dialog, or none to show (-p), is a no.
async function allowed($: EngineInterface, question: string): Promise<boolean> {
  if (mode === 'bypassPermissions') return true
  try {
    return (await $.ui.ask(question, ['Allow', 'Deny'])) === 'Allow'
  } catch {
    return false
  }
}

async function readTool($: EngineInterface, asked: unknown): Promise<string> {
  const current = partner!
  if (!(await allowed($, `Let this session read ${current.label}'s recent conversation?`))) return DECLINED
  const path = current.transcript
  if (!path || !home || !path.startsWith(`${home}/.claude/projects/`) || !path.endsWith('.jsonl') || path.includes('/../')) {
    return `${current.label}'s conversation cannot be read: the panel has no transcript for it.`
  }
  const run = await $.process.run(['tail', '-c', String(TAIL_BYTES), path])
  if (run.exitCode !== 0) return `${current.label}'s conversation cannot be read: ${run.stderr.trim()}`
  return readText(current.label, run.stdout, asked)
}

const WAIT_MS = 10 * 60_000
// Delegations whose tool call is still waiting; an answer for any other goes in as a message.
const waiting = new Set<string>()
let counter = 0

type Answer = { id: string; result: string; late: string }

async function readAnswer($: EngineInterface, id: string): Promise<Answer | null> {
  const path = `${folder}/answer-${id}.json`
  if (!(await $.fs.exists(path))) return null
  const value = await readJson($, path)
  const whole = value && value.id === id && typeof value.result === 'string' && typeof value.late === 'string'
  return whole ? value : null
}

async function delegateTool($: EngineInterface, input: Record<string, unknown>, signal: AbortSignal): Promise<string> {
  const current = partner!
  const task = typeof input.task === 'string' ? input.task : ''
  const why = typeof input.why === 'string' ? input.why : ''
  if (!(await allowed($, `Hand ${current.label} this task: ${firstWords(task)}?`))) return DECLINED
  const began = await $.clock.now()
  counter += 1
  const id = `${Math.floor(began).toString(36)}-${counter}`
  waiting.add(id)
  try {
    await writeWhole($, `delegate-${id}.json`, { id, partnership: current.id, task, why })
    await crossed($, current.me, current.label, 'asked')
    $.ui.toast(`Asked ${current.label}: ${firstWords(task)}`)
    if (current.state_note) $.ui.toast(current.state_note)
    const opening = current.state_note ? `${current.state_note}.\n\n` : ''
    while ((await $.clock.now()) - began < WAIT_MS) {
      if (signal.aborted) return `${current.label} keeps the task; its answer will come as a message.`
      const answer = await readAnswer($, id)
      if (answer) {
        await succeeded($, ['rm', '-f', `${folder}/answer-${id}.json`])
        await crossed($, current.me, current.label, 'answered')
        $.ui.toast(answer.result.split('\n')[0]!.slice(0, 80))
        return opening + answer.result
      }
      await $.process.run(['sleep', '2'])
    }
    return `${current.label} is still on it; its answer will come as a message.`
  } finally {
    waiting.delete(id)
  }
}

// An answer whose tool call gave up, was interrupted, or died with a reload: it goes in as a plugin prompt.
async function deliverLateAnswers($: EngineInterface, path: string): Promise<void> {
  for (const entry of await $.fs.list(path)) {
    if (!entry.name.startsWith('answer-') || !entry.name.endsWith('.json')) continue
    const id = entry.name.slice('answer-'.length, -'.json'.length)
    if (waiting.has(id)) continue
    const answer = await readAnswer($, id)
    if (!answer) continue
    await succeeded($, ['rm', '-f', `${path}/${entry.name}`])
    try {
      const entered = await $.prompt.submit({ text: answer.late })
      if (entered.drop !== undefined) $.ui.toast(`A late answer was not taken: ${entered.drop}`)
    } catch (error) {
      $.ui.toast(`A late answer was not taken: ${String(error)}`)
    }
    if (partner) await crossed($, partner.me, partner.label, 'answered')
  }
}

// A task the partner hands this session: taken from its own folder, submitted, its turn's first-Stop reply filed as
// the answer. And your last reply to you, filed for the partner's profile.

type TaskDrop = { link: string; nonce: string; role: 'task'; text: string; from: string; task: string; expires: number }
type Working = { link: string; nonce: string; from: string; turnId: string; stopped: string | null }

// Tasks taken and submitted, by nonce, until their turn starts.
const queued = new Map<string, { link: string; from: string; task: string }>()
// The task's turn; kept in the store too, so a reload mid-task still files its answer.
let working: Working | null = null
// A prompt you sent is waiting for its turn, and then that turn: its first Stop is your last reply.
let yoursNext = false
let yourTurn: string | null = null

async function remember($: EngineInterface): Promise<void> {
  const key = `task:${await $.session.id()}`
  if (working) await $.store.set(key, working)
  else await $.store.delete(key)
}

async function readTask($: EngineInterface, path: string): Promise<TaskDrop | null> {
  const drop = await readJson($, path)
  const whole = drop && drop.role === 'task' && typeof drop.text === 'string' && typeof drop.link === 'string'
    && typeof drop.nonce === 'string' && typeof drop.from === 'string' && typeof drop.expires === 'number'
  return whole ? { ...drop, task: typeof drop.task === 'string' ? drop.task : '' } : null
}

async function takeTasks($: EngineInterface, path: string): Promise<void> {
  const now = await $.clock.now()
  for (const entry of await $.fs.list(path)) {
    if (!entry.name.startsWith('task-') || !entry.name.endsWith('.json')) continue
    const drop = await readTask($, `${path}/${entry.name}`)
    if (!drop || !(drop.expires * 1000 >= now)) continue
    if (!(await succeeded($, ['mv', `${path}/${entry.name}`, `${path}/taken-${drop.link}.json`]))) continue
    queued.set(drop.nonce, { link: drop.link, from: drop.from, task: drop.task })
    let refused: string | null = null
    try {
      const entered = await $.prompt.submit({ text: drop.text })
      if (entered.drop !== undefined) refused = `the session did not take the task: ${entered.drop}`
    } catch (error) {
      refused = `the session did not take the task: ${String(error)}`
    }
    if (refused) {
      queued.delete(drop.nonce)
      await writeWhole($, `failed-${drop.link}.json`, { link: drop.link, reason: refused })
    }
  }
}

// The partner's part of turn.start: a prompt you sent begins your turn; a task's prompt begins the task's turn.
async function partnerTurnStart($: EngineInterface, e: TurnStartInput): Promise<void> {
  if (yoursNext) {
    yourTurn = e.turnId
    yoursNext = false
  }
  for (const [nonce, task] of queued) {
    if (!e.text.includes(`(link ${nonce})`)) continue
    queued.delete(nonce)
    working = { link: task.link, nonce, from: task.from, turnId: e.turnId, stopped: null }
    await remember($)
    await writeWhole($, `started-${task.link}.json`, {})
    $.ui.toast(`“${task.from}” asked you: ${task.task}`)
    await crossed($, `“${task.from}”`, partner?.me ?? '', 'asked')
    break
  }
}

// The partner's part of the first Stop, which carries the turn's reply before any Stop hook answers it.
async function partnerStop($: EngineInterface, e: { stop_hook_active: boolean; last_assistant_message?: string | null }): Promise<void> {
  if (e.stop_hook_active) return
  if (working && working.turnId === running && working.stopped === null) {
    working.stopped = e.last_assistant_message ?? ''
    await remember($)
  } else if (yourTurn && yourTurn === running) {
    const text = e.last_assistant_message ?? ''
    if (text.trim()) await writeWhole($, 'reply.json', { text, at: await $.clock.now() })
    yourTurn = null
  }
}

// The partner's part of turn.complete, a subagent's aside: the task's answer is filed, or why it has none.
async function partnerTurnComplete($: EngineInterface, e: TurnCompleteInput): Promise<void> {
  if (e.turnId === yourTurn) yourTurn = null
  if (!working || working.turnId !== e.turnId) return
  const { link, nonce, from, stopped } = working
  working = null
  await remember($)
  const text = stopped?.trim() ? stopped : e.answer
  const failed = stopped?.trim() ? null : FAILED[e.reason] ?? (e.answer.trim() ? null : 'the turn ended without an answer')
  if (failed) await writeWhole($, `failed-${link}.json`, { link, reason: failed })
  else await writeWhole($, `result-${link}.json`, { link, nonce, text })
  await crossed($, `“${from}”`, partner?.me ?? '', 'answered')
}

// The partner's part of prompt.submit -> why your prompt goes back to the box, or null to let it in. A prompt you
// type during a task's turn would join the answer that goes back.
async function partnerHeldPrompt($: EngineInterface, e: PromptSubmitInput): Promise<string | null> {
  const yours = e.origin.kind === 'composer' || e.origin.kind === 'bridge'
  if (yours && working && running === working.turnId) {
    await $.prompt.fill({ text: e.text })
    $.ui.toast(`“${working.from}”'s task is running; send this when it ends`)
    return `“${working.from}”'s task is running`
  }
  if (yours) yoursNext = true
  return null
}

async function registerPartnerTools($: EngineInterface): Promise<void> {
  tools.read = (await $.tool.register({
    name: 'partner_read',
    description: 'Reads the latest exchanges (prompts and replies) of the Claude Code session this one is linked '
      + 'with in the agents sidebar. Only works while the two are linked.',
    inputSchema: { type: 'object', properties: { turns: { type: 'integer', minimum: 1, maximum: TURNS_MAX,
      description: 'How many of the latest exchanges to read (default 3).' } } },
  })).tool
  tools.delegate = (await $.tool.register({
    name: 'partner_delegate',
    description: 'Hands the linked partner session a task and waits for its answer (up to ten minutes; a later '
      + 'answer arrives as a message). One task at a time between the two.',
    inputSchema: { type: 'object', required: ['task', 'why'], properties: {
      task: { type: 'string', description: 'The task, written for the partner to act on.' },
      why: { type: 'string', description: 'Why the partner is the better fit for it, in one line.' } } },
  })).tool
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await failTakenAsks($)
    const kept = await $.store.get(`task:${await $.session.id()}`)
    if (kept && typeof kept === 'object') working = kept as Working
    $.clock.every(TICK_MS, () => { void tick($) })
    await registerPartnerTools($)
    $.clock.every(TICK_MS, () => { void partnerTick($) })
    return started
  })

  // The serving hook for both partner tools; any other tool passes on untouched.
  on('tool.call', async ($, e, next) => {
    if (e.tool !== tools.read && e.tool !== tools.delegate) return next(e)
    // An MCP tool's input carries its own arguments untyped beside the envelope.
    const input = e as unknown as Record<string, unknown>
    if (input.agentId) return { result: FROM_SUBAGENT }
    if (!partner) return { result: (await linkingOn($)) ? NOT_LINKED : LINKING_OFF }
    if (e.tool === tools.read) return { result: await readTool($, input.turns) }
    return { result: await delegateTool($, input, next.signal) }
  })

  // What the model is told of its partner rides on the prompt, never in the system prompt, which Claude Code reads
  // once per conversation: the introduction once per pairing and conversation, a profile when it changed, the untie.
  on('classic.UserPromptSubmit', async ($, e, next) => {
    const result = await next(e)
    if (typeof e.permission_mode === 'string') mode = e.permission_mode
    const key = `given:${await $.session.id()}`
    const given = (await $.store.get(key)) as { pair: string; key: string; label: string } | undefined
    let told: string | null = null
    if (partner && given?.pair !== partner.id) told = partner.introduction
    else if (partner && given?.key !== partner.key) told = `What the panel knows of your partner ${partner.label} now:\n${partner.profile}`
    else if (!partner && given) told = `You are no longer linked with ${given.label}; the partner tools now answer that.`
    if (told === null) return result
    if (partner) await $.store.set(key, { pair: partner.id, key: partner.key, label: partner.label })
    else await $.store.delete(key)
    return { ...result, additionalContext: [...(result.additionalContext ?? []), told] }
  })

  on('turn.start', async ($, e, next) => {
    // A subagent's run raises no turn.start, so the running turn is always the main loop's.
    running = e.turnId
    if (asked && asked.turnId === null && e.text.includes(`(link ${asked.nonce})`)) asked.turnId = e.turnId
    for (const [nonce, delivery] of delivering) {
      if (!e.text.includes(`(link ${nonce})`)) continue
      delivering.delete(nonce)
      await writeWhole($, `started-${delivery.link}.json`, {})
      const now = await $.clock.now()
      band = { from: delivery.from, to: delivery.to, fromHue: delivery.fromHue, toHue: delivery.toHue, state: 'delivered', since: now, until: now + CLEAR_MS }
      animate($)
      $.ui.toast(`“${delivery.from}” handed you its latest result`)
      $.ui.invalidate('ui.render')
      break
    }
    await partnerTurnStart($, e)
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId) return next(e)
    if (e.turnId === running) running = null
    if (asked && asked.turnId === e.turnId) {
      const { link, nonce, to, stopped } = asked
      asked = null
      // A reply the turn stopped with is the result, whatever a hook sent the turn on to do after it.
      const text = stopped?.trim() ? stopped : e.answer
      const failed = stopped?.trim() ? null : FAILED[e.reason] ?? (e.answer.trim() ? null : 'the turn ended without an answer')
      if (failed) {
        await writeWhole($, `failed-${link}.json`, { link, reason: failed })
        $.ui.toast(`The link to “${to}” failed: ${failed}`)
      } else {
        await writeWhole($, `result-${link}.json`, { link, nonce, text })
        $.ui.toast(`Sent your latest result to “${to}”`)
      }
      const now = await $.clock.now()
      if (band) band = { ...band, state: 'sent', since: now, until: now + CLEAR_MS }
      animate($)
      $.ui.invalidate('ui.render')
    }
    await partnerTurnComplete($, e)
    return next(e)
  })

  // The asked turn's first Stop carries its reply before any Stop hook answers; later Stops in the same turn
  // carry the replies to those hooks.
  on('classic.Stop', async ($, e, next) => {
    if (asked?.turnId && !e.stop_hook_active) {
      asked.stopped = e.last_assistant_message ?? ''
    }
    await partnerStop($, e)
    return next(e)
  })

  // A prompt you type during the hand-off would join its reply; it goes back to the box instead.
  on('prompt.submit', async ($, e, next) => {
    const yours = e.origin.kind === 'composer' || e.origin.kind === 'bridge'
    if (!yours || !asked?.turnId || running !== asked.turnId) {
      const held = await partnerHeldPrompt($, e)
      return held === null ? next(e) : { drop: held }
    }
    // The box takes text alone, so an image or file sent with the prompt has to be added again.
    await $.prompt.fill({ text: e.text })
    const attached = e.attachments?.[0]
    const extra = attached ? `, and add the ${attached.type} again` : ''
    $.ui.toast(`the hand-off is running; send this when it ends${extra}`)
    return { drop: 'the hand-off is running' }
  }).catch(($, e, next) => next(e))

  // On the right: each session as a chip, joined by a link that flows while A writes and locks once sent, then the state.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (!band && crossing) {
      // A partner crossing: `‹A› 🔗 ‹B› · asked`, then answered.
      const { Box, Text } = $.ui.resolve(e)
      const hue = crossing.state === 'asked' ? '#4a8fd6' : '#3fa66b'
      return (
        <Box width={e.props.bodyColumns} justifyContent="flex-end">
          <Text color={hue}>{`${crossing.from} 🔗 ${crossing.to} · ${crossing.state}`}</Text>
        </Box>
      )
    }
    if (!band) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const now = await $.clock.now()
    const frame = Math.floor((now - band.since) / FRAME_MS)
    const writing = band.state === 'writing'
    const link = writing ? FLOW[frame % FLOW.length]! : '━━━'
    const mark = writing ? SPINNER[frame % SPINNER.length]! : '✓'
    const hue = STATE_HUE[band.state]
    return (
      <Box width={e.props.bodyColumns} justifyContent="flex-end">
        <Text>
          <Text backgroundColor={band.fromHue} color="#ffffff">{` ${band.from} `}</Text>
          <Text color={hue}>{` ${link} 🔗 ${link} `}</Text>
          <Text backgroundColor={band.toHue} color="#ffffff">{` ${band.to} `}</Text>
          <Text color={hue} bold={now - band.since < FLASH_MS}>{` ${mark} ${band.state}`}</Text>
        </Text>
      </Box>
    )
  })
}
