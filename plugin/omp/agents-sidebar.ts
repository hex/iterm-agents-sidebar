// ABOUTME: Agents sidebar for iTerm2: reports this omp session's turns to the panel. Written by install.sh, which owns this file.
// ABOUTME: Each omp event becomes a Claude-shaped payload for the panel's state hook, run one child at a time.
// agents-sidebar-omp-extension: written by the Agents panel's install.sh, which owns this file.

import { dirname } from "node:path";

type Env = Record<string, string | undefined>;

/**
 * Whether this extension instance speaks for the pane: omp's interactive
 * session, in the terminal. A subagent runs its own instance with no UI, a
 * print or RPC run has no pane of its own, and an omp started from another
 * omp's shell (omp marks those with OMPCODE=1) would report over its parent.
 * Decided before any identity is taken.
 */
export function accepted(ctx: { hasUI?: unknown; mode?: unknown } | undefined, env: Env): boolean {
  return env.OMPCODE !== "1" && ctx?.hasUI === true && ctx?.mode === "tui";
}

/** The most of each part of a question a payload carries, as the hook clips them. */
const QUESTION_LIMIT = 300;
const HEADER_LIMIT = 40;
const OPTION_LIMIT = 60;
/** The most questions, and options per question, a payload carries. */
const QUESTIONS_MAX = 10;
const OPTIONS_MAX = 20;

function clip(text: unknown, limit: number): string {
  const whole = typeof text === "string" ? text : "";
  return whole.length <= limit ? whole : whole.slice(0, limit - 1) + "…";
}

function listOf(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/**
 * omp's ask arguments -> the AskUserQuestion input the hook reads: the
 * header, question and option labels of each, nothing else. An option's
 * description and preview are text the card has no room for.
 */
function askedInput(args: unknown): { questions: unknown[] } {
  const questions = listOf((args as { questions?: unknown } | undefined)?.questions).slice(0, QUESTIONS_MAX);
  return {
    questions: questions.map(asked => {
      const each = (asked ?? {}) as { header?: unknown; question?: unknown; options?: unknown; multi?: unknown };
      return {
        header: clip(each.header, HEADER_LIMIT),
        question: clip(each.question, QUESTION_LIMIT),
        options: listOf(each.options).slice(0, OPTIONS_MAX)
          .map(option => ({ label: clip((option as { label?: unknown } | undefined)?.label, OPTION_LIMIT) })),
        multiSelect: each.multi === true,
      };
    }),
  };
}

/** The most of a command or path a payload carries; the hook shows less. */
const GIVEN_LIMIT = 300;
/** The arguments that name what a call does, in the hook's own words. */
const NAMING = ["command", "file_path", "path"] as const;

/**
 * A tool call's arguments -> the part an approval card shows (the command, or
 * the path), clipped; undefined when they hold none. Never the rest: a write
 * call's arguments are the whole file.
 */
export function givenTo(args: unknown): Record<string, string> | undefined {
  if (typeof args !== "object" || args === null) return undefined;
  const named: Record<string, string> = {};
  for (const key of NAMING) {
    const value = (args as Record<string, unknown>)[key];
    if (typeof value === "string") named[key] = clip(value, GIVEN_LIMIT);
  }
  return Object.keys(named).length ? named : undefined;
}

/** What every payload carries: the session's id and omp's own pid, since ps calls omp `bun`. */
export type Common = { session_id: string; pid: number };
export type Payload = Common & Record<string, unknown>;
/** One run of the state hook: the Claude Code hook event omp's event reads as, and its stdin. */
export type Hook = { event: string; payload: Payload };
type OmpEvent = { type: string; [field: string]: unknown };

/**
 * An omp event -> the hook run it reads as, or undefined for one that says
 * nothing about the session's state.
 *
 * `input` is no turn start: an input an extension handles runs no turn, and
 * `agent_start` alone starts one. An `agent_end` that omp follows with a
 * continuation of its own (a retry) is no turn end.
 */
export function hookFor(event: OmpEvent, common: Common, given?: Record<string, unknown>): Hook | undefined {
  const call = { ...common, tool_use_id: event.toolCallId };
  switch (event.type) {
    case "tool_execution_start":
      // omp's ask is its own dialog; the hook's fold knows a question waiting
      // on you as Claude Code's AskUserQuestion permission prompt.
      return event.toolName === "ask"
        ? { event: "Notification",
            payload: { ...call, notification_type: "permission_prompt", tool_name: "AskUserQuestion",
                       tool_input: askedInput(event.args) } }
        : { event: "PreToolUse", payload: { ...call, tool_name: event.toolName } };
    case "tool_execution_end":
      return { event: event.isError === true ? "PostToolUseFailure" : "PostToolUse", payload: call };
    case "tool_approval_requested":
      // The approval names no arguments; what the call was given comes from
      // its start, when that reached us first.
      return { event: "PermissionRequest",
               payload: { ...call, tool_name: event.toolName, ...(given ? { tool_input: given } : {}) } };
    case "tool_approval_resolved":
      return { event: event.approved === true ? "PostToolUse" : "PermissionDenied", payload: call };
    case "session_start":
    case "session_switch":
    case "session_branch":
      return { event: "SessionStart", payload: { ...common } };
    case "agent_start":
      return { event: "UserPromptSubmit", payload: { ...common } };
    case "agent_end":
      return event.willContinue === true ? undefined : { event: "Stop", payload: { ...common } };
    case "session_shutdown":
      return { event: "SessionEnd", payload: { ...common } };
    default:
      return undefined;
  }
}

/**
 * What the hook needs of omp's environment, and nothing else: HOME for its
 * state files, PATH, TMUX to wrap its escape for tmux, and TTY when omp has
 * it. Without TTY the hook finds the pane's terminal from its parent, omp.
 */
export function childEnv(env: Env): Record<string, string> {
  const kept: Record<string, string> = {};
  for (const key of ["HOME", "PATH", "TMUX", "TTY"]) {
    const value = env[key];
    if (value) kept[key] = value;
  }
  return kept;
}

/**
 * How long one run of the hook may take before it is killed: the bound on a
 * hung child, not on a slow one. A run killed is a report lost, a gate's
 * closing among them. Measured on a Mac at load average 72: python's start
 * alone took 250 ms (464 ms at worst), and Xcode's /usr/bin/python3 took
 * 1.9 s on its first run. Nothing in omp waits on it; the reports queued
 * behind it do. Ten seconds, as Codex is given for the same hook.
 */
const RUN_TIMEOUT_MS = 10_000;

/**
 * A runner that starts the state hook as `python -B <handler> <Event> --agent
 * omp` with the payload on stdin and waits for it to exit. No shell, nothing
 * read back, and every failure is that report lost and nothing more.
 */
export function spawnHandler(python: string, handler: string, env: Record<string, string>,
                             timeoutMs = RUN_TIMEOUT_MS): Runner {
  return async hook => {
    try {
      const child = Bun.spawn([python, "-B", handler, hook.event, "--agent", "omp"], {
        cwd: dirname(handler),
        env,
        stdin: new TextEncoder().encode(JSON.stringify(hook.payload)),
        stdout: "ignore",
        stderr: "ignore",
        timeout: timeoutMs,
        killSignal: "SIGKILL",
      });
      await child.exited;
    } catch {
      // No python, no handler, or no process to spare: the panel misses this
      // report, and omp must never hear of it.
    }
  };
}

/** The most reports waiting on the hook. A turn's events come a few a second at most. */
const QUEUE_LIMIT = 64;

/** How often an open turn says it is still working: well inside the panel's five minutes. */
const BEAT_MS = 120_000;
/** Reports after which no turn is open. */
const TURN_OVER = new Set(["Stop", "SessionEnd", "SessionStart"]);

/** Runs the state hook once. */
export type Runner = (hook: Hook) => Promise<void>;

/**
 * The reports of one omp session, run through the hook one at a time.
 *
 * omp calls its subscribers without waiting for them, and the hook writes
 * the terminal after it lets go of its own lock, so two runs side by side
 * could publish the older state last. `send` only queues and returns: omp
 * waits on its approval handlers before it shows the prompt.
 */
export class Reporter {
  readonly #run: Runner;
  readonly #limit: number;
  #queue: Hook[] = [];
  #working = false;
  #stopped = false;
  #waiters: Array<() => void> = [];

  readonly #beatMs: number;
  #beat: ReturnType<typeof setInterval> | undefined;

  constructor(run: Runner, limit = QUEUE_LIMIT, beatMs = BEAT_MS) {
    this.#run = run;
    this.#limit = limit;
    this.#beatMs = beatMs;
  }

  /**
   * True from the time more reports waited than the queue holds until
   * another session takes the pane. Dropping one could drop a gate closing
   * while omp works on, and a blocked claim never ages, so the overflow
   * drops them all and reports the session's end in their place: the card
   * falls back to what omp's title says. Nothing else of the session is
   * reported after that but its end.
   */
  get stopped(): boolean {
    return this.#stopped;
  }

  send(hook: Hook): void {
    if (this.#stopped) return;
    if (this.#queue.length >= this.#limit) {
      this.#stopped = true;
      this.#quiet();
      const { session_id, pid } = hook.payload;
      this.#queue = [{ event: "SessionEnd", payload: { session_id, pid } }];
      void this.#work();
      return;
    }
    if (hook.event === "UserPromptSubmit") this.#beatFor(hook.payload);
    else if (TURN_OVER.has(hook.event)) this.#quiet();
    this.#queue.push(hook);
    void this.#work();
  }

  /** The pane now shows another session: what still waited for the one before is dropped. */
  newSession(): void {
    this.#queue = [];
    this.#stopped = false;
    this.#quiet();
  }

  /**
   * The session's end, ahead of whatever still waits: the end clears the
   * session's state, so those would change nothing, and omp gives its
   * shutdown two seconds. -> resolves once the end has run.
   */
  end(hook: Hook): Promise<void> {
    this.#queue = [];
    this.#stopped = false;
    this.send(hook);
    return this.drained();
  }

  /**
   * While a turn is open, say it is still working on every beat. The panel
   * reads a working claim older than five minutes as unknown, and one long
   * tool call or answer sends nothing. The beat is a tool start that names
   * no tool: it opens and closes nothing, and resending the turn's own start
   * would restart its clock and close any prompt still waiting on you.
   */
  #beatFor(payload: Payload): void {
    this.#quiet();
    const common = { session_id: payload.session_id, pid: payload.pid };
    this.#beat = setInterval(() => this.send({ event: "PreToolUse", payload: { ...common } }), this.#beatMs);
    // A beat must never be what keeps omp from exiting.
    this.#beat.unref?.();
  }

  #quiet(): void {
    clearInterval(this.#beat);
    this.#beat = undefined;
  }

  /** Resolves once no report waits and none is running. Never rejects. */
  drained(): Promise<void> {
    if (!this.#working) return Promise.resolve();
    return new Promise(resolve => this.#waiters.push(resolve));
  }

  async #work(): Promise<void> {
    if (this.#working) return;
    this.#working = true;
    while (this.#queue.length) {
      try {
        await this.#run(this.#queue.shift()!);
      } catch {
        // A run that fails costs its report; a rejection that escaped here
        // would reach omp's fatal handler and end the user's session.
      }
    }
    this.#working = false;
    for (const resolve of this.#waiters.splice(0)) resolve();
  }
}

type Handler = (event: OmpEvent, ctx: Ctx) => unknown;
/** The part of omp's extension API this uses. */
type Api = { on(event: string, handler: Handler): void };
type Ctx = { hasUI?: unknown; mode?: unknown; sessionManager?: { getSessionId?: () => unknown } } | undefined;

/** The omp events that say something about the session's state; the rest are never subscribed. */
const EVENTS = ["session_start", "session_switch", "session_branch", "agent_start", "tool_execution_start",
                "tool_approval_requested", "tool_approval_resolved", "tool_execution_end", "agent_end",
                "session_shutdown"];
/** Events after which the pane shows another session. */
const SWITCHES = new Set(["session_switch", "session_branch"]);
/** The most tool calls whose arguments are held for an approval that may follow. */
const GIVEN_MAX = 64;

/**
 * Subscribes to omp's events and reports them through `run`. -> the reporter.
 *
 * The session spoken for is taken only from an instance `accepted` passes,
 * so a subagent's copy of this extension never takes one and reports
 * nothing. Every handler returns without waiting, but the shutdown's, which
 * omp waits on (two seconds at most) while the session's end reaches the hook.
 */
export function register(pi: Api, env: Env, run: Runner, pid: number): Reporter {
  const reporter = new Reporter(run);
  let session: string | undefined;
  const given = new Map<string, Record<string, string>>();

  const idOf = (ctx: Ctx): string | undefined => {
    if (!accepted(ctx, env)) return undefined;
    const id = ctx?.sessionManager?.getSessionId?.();
    return typeof id === "string" && id ? id : undefined;
  };

  const handle = (event: OmpEvent, ctx: Ctx): unknown => {
    if (SWITCHES.has(event.type)) {
      const id = idOf(ctx);
      if (!id) return undefined;
      session = id;
      given.clear();
      reporter.newSession();
    } else {
      // An extension loaded into a session already under way sees no start.
      session ??= idOf(ctx);
    }
    if (!session) return undefined;
    const call = typeof event.toolCallId === "string" ? event.toolCallId : "";
    if (event.type === "tool_execution_start") {
      const named = givenTo(event.args);
      if (named && given.size < GIVEN_MAX) given.set(call, named);
    }
    const hook = hookFor(event, { session_id: session, pid }, given.get(call));
    if (event.type === "tool_execution_end") given.delete(call);
    if (!hook) return undefined;
    if (event.type === "session_shutdown") return reporter.end(hook);
    reporter.send(hook);
    return undefined;
  };

  for (const name of EVENTS) {
    pi.on(name, (event, ctx) => {
      try {
        return handle(event, ctx);
      } catch {
        // A throw here reaches omp; the panel misses one report instead.
        return undefined;
      }
    });
  }
  return reporter;
}

/** Filled in by install.sh: the python it found and the state hook it installed. */
const PYTHON = "@AGENTS_SIDEBAR_PYTHON@";
const HANDLER = "@AGENTS_SIDEBAR_HANDLER@";

export default function agentsSidebar(pi: Api): void {
  register(pi, process.env, spawnHandler(PYTHON, HANDLER, childEnv(process.env)), process.pid);
}
