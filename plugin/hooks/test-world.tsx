// ABOUTME: Everything beneath the link mod, in memory, for its kit tests: the session's folder as a map of paths,
// ABOUTME: mkdir/chmod/mv/rm/tail/sleep, the store, the session id, and the hooks the engine would answer.
import { mock } from 'claude-code/testing'
import type { On } from 'claude-code'

export const HOME = '/home/test'
export const folderOf = (id: string) => `${HOME}/.claude/agents-sidebar-links/${id}`
export const F = folderOf('sess-1')
export const TRANSCRIPT = `${HOME}/.claude/projects/-work-bravo/b-id.jsonl`
export const READ = 'mcp__agents-sidebar__partner_read'
export const DELEGATE = 'mcp__agents-sidebar__partner_delegate'
export const SETTINGS = `${HOME}/.claude/agents-sidebar-settings.json`

export type World = {
  files: Map<string, string>; submitted: string[]; filled: string[]; toasts: string[]
  id: string; store: Map<string, unknown>; tail: string | null; runs: string[][]
  // The test's mock clock, which `sleep` advances, and what to do after each sleep (plant an answer, look at the band).
  clock: any; onSleep: (() => unknown) | null
  // Why the engine refuses a tool's registration, by name, as a managed allowedMcpServers would; null registers it.
  refuses: ((name: string) => string | null) | null
}

// Everything beneath the mod: its folder as a map of paths, mkdir/chmod/mv/rm/tail/sleep, the store, the dialog.
// The panel's settings have linking turned on.
export function world(on: On): World {
  const w: World = { files: new Map([[SETTINGS, JSON.stringify({ links: true })]]), submitted: [], filled: [], toasts: [], id: 'sess-1',
    store: new Map(), tail: null, runs: [], clock: null, onSleep: null, refuses: null }
  const dirOf = (path: string) => path.slice(0, path.lastIndexOf('/'))
  mock.env(on, { HOME })
  on('session.id', () => ({ value: w.id }))
  on('fs.write', ($, e) => { w.files.set(e.path, e.text); return { value: undefined } })
  on('fs.read', ($, e) => {
    const text = w.files.get(e.path)
    if (text === undefined) throw new Error(`ENOENT: ${e.path}`)
    return { value: text }
  })
  on('fs.exists', ($, e) => ({ value: w.files.has(e.path) }))
  on('fs.list', ($, e) => ({ value: [...w.files.keys()].filter(path => dirOf(path) === e.path).map(path => ({
    name: path.slice(e.path.length + 1), kind: 'file' as const, size: w.files.get(path)!.length, mtimeMs: 0, isLink: false,
  })) }))
  on('process.run', async ($, e) => {
    const [command, ...args] = e.argv
    w.runs.push([...e.argv])
    if (command === 'sleep') {
      if (w.clock) await w.clock.advance(Number(args[0]) * 1000)
      await w.onSleep?.()
    }
    let exitCode = 0
    let stdout = ''
    if (command === 'mv') {
      const text = w.files.get(args[0]!)
      if (text === undefined) exitCode = 1
      else { w.files.delete(args[0]!); w.files.set(args[1]!, text) }
    } else if (command === 'rm') {
      for (const path of args) w.files.delete(path)
    } else if (command === 'tail') {
      if (w.tail === null) exitCode = 1
      else stdout = w.tail
    } else if (command !== 'mkdir' && command !== 'chmod' && command !== 'sleep') {
      exitCode = 127
    }
    return { value: { exitCode, stdout, stderr: exitCode ? 'no such file' : '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('store.get', ($, e) => ({ value: w.store.get(e.key) }))
  on('store.set', ($, e) => { w.store.set(e.key, e.value); return { value: undefined } })
  on('store.delete', ($, e) => { w.store.delete(e.key); return { value: undefined } })
  on('tool.register', ($, e) => {
    const refused = w.refuses?.(e.name) ?? null
    return refused === null ? { value: { tool: `mcp__agents-sidebar__${e.name}` } } : { deny: refused }
  })
  on('prompt.submit', ($, e) => { w.submitted.push(e.text); return { text: e.text } })
  on('prompt.fill', ($, e) => { w.filled.push(e.text); return { isFilled: true } })
  on('ui.toast', ($, e) => { w.toasts.push(e.text); return { value: undefined } })
  on('ui.invalidate', () => ({ value: undefined }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('turn.complete', ($, e) => ({ text: e.answer }))
  on('session.append', ($, e, next) => next(e))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box />
  })
  return w
}
