// ABOUTME: Tests the omp extension: which session it speaks for, what each event sends, the queue that
// ABOUTME: runs the state hook one child at a time, and the child itself. Run with `bun test` in this directory.
import { afterAll, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { accepted, childEnv, givenTo, type Hook, hookFor, register, Reporter, spawnHandler } from "./agents-sidebar.ts";

const tui = { hasUI: true, mode: "tui" };
const common = { session_id: "019a0c5e-7d1e-7c55-9a53-2f6f0c1d8e11", pid: 4242 };

describe("a turn's life", () => {
  test("a session opening, switched to or branched reads as a session start", () => {
    for (const type of ["session_start", "session_switch", "session_branch"]) {
      expect(hookFor({ type }, common)).toEqual({ event: "SessionStart", payload: common });
    }
  });

  test("the agent starting is the turn starting; input alone is not", () => {
    expect(hookFor({ type: "agent_start" }, common)).toEqual({ event: "UserPromptSubmit", payload: common });
    expect(hookFor({ type: "input", text: "hello" }, common)).toBeUndefined();
  });

  test("the agent ending is the turn ending, unless omp has already scheduled more", () => {
    expect(hookFor({ type: "agent_end", messages: [] }, common)).toEqual({ event: "Stop", payload: common });
    expect(hookFor({ type: "agent_end", messages: [], willContinue: false }, common))
      .toEqual({ event: "Stop", payload: common });
    expect(hookFor({ type: "agent_end", messages: [], willContinue: true }, common)).toBeUndefined();
  });

  test("the session shutting down ends it", () => {
    expect(hookFor({ type: "session_shutdown" }, common)).toEqual({ event: "SessionEnd", payload: common });
  });
});

describe("tools", () => {
  const start = { type: "tool_execution_start", toolCallId: "call_7", toolName: "bash", args: { command: "ls" } };

  test("a tool starting and ending, by its call id", () => {
    expect(hookFor(start, common)).toEqual({
      event: "PreToolUse", payload: { ...common, tool_use_id: "call_7", tool_name: "bash" } });
    const end = { type: "tool_execution_end", toolCallId: "call_7", toolName: "bash", result: "x", isError: false };
    expect(hookFor(end, common)).toEqual({ event: "PostToolUse", payload: { ...common, tool_use_id: "call_7" } });
    expect(hookFor({ ...end, isError: true }, common))
      .toEqual({ event: "PostToolUseFailure", payload: { ...common, tool_use_id: "call_7" } });
  });

  test("an approval asked opens a gate on its call, with what the call was given when that is known", () => {
    const asked = { type: "tool_approval_requested", sessionId: "s", toolCallId: "call_7", toolName: "bash",
                    reason: "matches a rule", approvalMode: "always-ask" };
    expect(hookFor(asked, common, { command: "git push" })).toEqual({
      event: "PermissionRequest",
      payload: { ...common, tool_use_id: "call_7", tool_name: "bash", tool_input: { command: "git push" } } });
    expect(hookFor(asked, common)).toEqual({
      event: "PermissionRequest", payload: { ...common, tool_use_id: "call_7", tool_name: "bash" } });
  });

  test("an approval answered closes its gate, allowed or refused", () => {
    const resolved = { type: "tool_approval_resolved", sessionId: "s", toolCallId: "call_7", toolName: "bash" };
    expect(hookFor({ ...resolved, approved: true }, common))
      .toEqual({ event: "PostToolUse", payload: { ...common, tool_use_id: "call_7" } });
    expect(hookFor({ ...resolved, approved: false }, common))
      .toEqual({ event: "PermissionDenied", payload: { ...common, tool_use_id: "call_7" } });
  });

  test("what a call was given is kept to what names it: the command or the path, clipped", () => {
    expect(givenTo({ path: "src/app.ts", content: "a whole file" })).toEqual({ path: "src/app.ts" });
    expect(givenTo({ command: "x".repeat(500) })).toEqual({ command: "x".repeat(299) + "…" });
    expect(givenTo({ file_path: "/tmp/a", command: "ls" })).toEqual({ command: "ls", file_path: "/tmp/a" });
    expect(givenTo({ pattern: "TODO" })).toBeUndefined();
    expect(givenTo({ command: 7 })).toBeUndefined();
    expect(givenTo("ls")).toBeUndefined();
    expect(givenTo(undefined)).toBeUndefined();
  });

  test("an ask carries at most ten questions of twenty options, each part clipped", () => {
    const option = { label: "o".repeat(80) };
    const asked = { question: "q".repeat(400), header: "h".repeat(50), options: Array(25).fill(option) };
    const ask = { type: "tool_execution_start", toolCallId: "call_9", toolName: "ask",
                  args: { questions: Array(12).fill(asked) } };
    const questions = (hookFor(ask, common)!.payload.tool_input as { questions: any[] }).questions;
    expect(questions.length).toBe(10);
    expect(questions[0]).toEqual({ header: "h".repeat(39) + "…", question: "q".repeat(299) + "…",
                                   options: Array(20).fill({ label: "o".repeat(59) + "…" }),
                                   multiSelect: false });
  });

  test("the ask tool starting is a question waiting on you, in the shape of Claude Code's", () => {
    const ask = { type: "tool_execution_start", toolCallId: "call_8", toolName: "ask",
                  args: { questions: [{ id: "q1", question: "Which branch?", header: "Scope",
                                        options: [{ label: "main", description: "the default" }, { label: "dev" }],
                                        multi: true, recommended: 0 }] } };
    expect(hookFor(ask, common)).toEqual({
      event: "Notification",
      payload: { ...common, notification_type: "permission_prompt", tool_use_id: "call_8",
                 tool_name: "AskUserQuestion",
                 tool_input: { questions: [{ header: "Scope", question: "Which branch?",
                                             options: [{ label: "main" }, { label: "dev" }], multiSelect: true }] } } });
  });
});

describe("the session it speaks for", () => {
  test("is the interactive one in the terminal", () => {
    expect(accepted(tui, {})).toBe(true);
  });

  test("is never a subagent, a print run or an RPC host", () => {
    expect(accepted({ hasUI: false, mode: "tui" }, {})).toBe(false);
    expect(accepted({ hasUI: true, mode: "rpc" }, {})).toBe(false);
    expect(accepted({ hasUI: true, mode: "print" }, {})).toBe(false);
    expect(accepted({ hasUI: "yes", mode: "tui" }, {})).toBe(false);
    expect(accepted(undefined, {})).toBe(false);
  });

  test("is never an omp started from another omp's shell", () => {
    expect(accepted(tui, { OMPCODE: "1" })).toBe(false);
  });
});

/** A hook runner each of whose runs waits until the test lets it finish. */
function heldRunner() {
  const log: string[] = [];
  const waiting: Array<() => void> = [];
  const run = (hook: Hook) => {
    log.push("start " + hook.event);
    return new Promise<void>(resolve => waiting.push(() => { log.push("end " + hook.event); resolve(); }));
  };
  const finishOne = async () => {
    waiting.shift()!();
    await Bun.sleep(1);
  };
  return { log, run, finishOne };
}

const hook = (event: string): Hook => ({ event, payload: { ...common } });

describe("the queue", () => {
  test("runs the hook for one report at a time, in the order they came", async () => {
    const { log, run, finishOne } = heldRunner();
    const reporter = new Reporter(run);
    for (const event of ["UserPromptSubmit", "PreToolUse", "Stop"]) reporter.send(hook(event));
    await Bun.sleep(1);
    expect(log).toEqual(["start UserPromptSubmit"]);
    await finishOne();
    await finishOne();
    await finishOne();
    expect(log).toEqual(["start UserPromptSubmit", "end UserPromptSubmit", "start PreToolUse", "end PreToolUse",
                         "start Stop", "end Stop"]);
  });

  test("a run that throws costs that report alone", async () => {
    const ran: string[] = [];
    const reporter = new Reporter(async h => {
      ran.push(h.event);
      if (h.event === "PreToolUse") throw new Error("spawn failed");
    });
    reporter.send(hook("PreToolUse"));
    reporter.send(hook("Stop"));
    await Bun.sleep(5);
    expect(ran).toEqual(["PreToolUse", "Stop"]);
  });

  test("once more are waiting than it holds, ends the session's claim and reports nothing more of it", async () => {
    const ran: Hook[] = [];
    const { log, run, finishOne } = heldRunner();
    const reporter = new Reporter(h => { ran.push(h); return run(h); }, 2);
    for (const event of ["PermissionRequest", "PostToolUse", "UserPromptSubmit", "PreToolUse"]) {
      reporter.send(hook(event));
    }
    expect(reporter.stopped).toBe(true);
    // The approval already running would otherwise stand as blocked while
    // omp lives: the panel ages only a working claim.
    await finishOne();
    expect(ran.at(-1)).toEqual({ event: "SessionEnd", payload: common });
    await finishOne();
    reporter.send(hook("Stop"));
    await Bun.sleep(5);
    expect(log).toEqual(["start PermissionRequest", "end PermissionRequest", "start SessionEnd", "end SessionEnd"]);
  });

  test("reports again after an overflow once another session takes the pane", async () => {
    const { log, run, finishOne } = heldRunner();
    const reporter = new Reporter(run, 1);
    for (const event of ["UserPromptSubmit", "PreToolUse", "PostToolUse"]) reporter.send(hook(event));
    await finishOne();
    await finishOne();
    reporter.newSession();
    expect(reporter.stopped).toBe(false);
    reporter.send(hook("SessionStart"));
    await finishOne();
    expect(log).toEqual(["start UserPromptSubmit", "end UserPromptSubmit", "start SessionEnd", "end SessionEnd",
                         "start SessionStart", "end SessionStart"]);
  });

  test("reports the session's end after an overflow", async () => {
    const ran: string[] = [];
    const reporter = new Reporter(async h => { ran.push(h.event); }, 0);
    reporter.send(hook("UserPromptSubmit"));
    await Bun.sleep(5);
    await reporter.end(hook("SessionEnd"));
    expect(ran).toEqual(["SessionEnd", "SessionEnd"]);
  });

  test("a switch to another session drops what was still waiting for the one before", async () => {
    const { log, run, finishOne } = heldRunner();
    const reporter = new Reporter(run);
    reporter.send(hook("UserPromptSubmit"));
    reporter.send(hook("PreToolUse"));
    reporter.newSession();
    reporter.send(hook("SessionStart"));
    await finishOne();
    await finishOne();
    expect(log).toEqual(["start UserPromptSubmit", "end UserPromptSubmit", "start SessionStart", "end SessionStart"]);
  });

  test("is drained once every report waiting has run", async () => {
    const { log, run, finishOne } = heldRunner();
    const reporter = new Reporter(run);
    let drained = false;
    expect(await Promise.race([reporter.drained(), Bun.sleep(5).then(() => "waiting")])).toBeUndefined();
    reporter.send(hook("Stop"));
    reporter.send(hook("SessionEnd"));
    void reporter.drained().then(() => { drained = true; });
    await finishOne();
    expect(drained).toBe(false);
    await finishOne();
    expect(drained).toBe(true);
    expect(log).toEqual(["start Stop", "end Stop", "start SessionEnd", "end SessionEnd"]);
  });
});

describe("a turn that goes quiet", () => {
  test("is said to be working again on every beat until it ends, without opening or closing anything", async () => {
    const ran: Hook[] = [];
    const reporter = new Reporter(async h => { ran.push(h); }, 64, 20);
    reporter.send(hook("UserPromptSubmit"));
    await Bun.sleep(70);
    reporter.send(hook("Stop"));
    const beats = ran.slice(1, -1);
    expect(ran[0].event).toBe("UserPromptSubmit");
    expect(ran.at(-1)!.event).toBe("Stop");
    expect(beats.length).toBeGreaterThanOrEqual(2);
    for (const beat of beats) expect(beat).toEqual({ event: "PreToolUse", payload: common });
    await Bun.sleep(60);
    expect(ran.at(-1)!.event).toBe("Stop");
  });

  test("beats no more once its session ends or another takes the pane", async () => {
    for (const end of [(r: Reporter) => r.send(hook("SessionEnd")), (r: Reporter) => r.newSession(),
                       (r: Reporter) => r.send(hook("SessionStart"))]) {
      const ran: string[] = [];
      const reporter = new Reporter(async h => { ran.push(h.event); }, 64, 20);
      reporter.send(hook("UserPromptSubmit"));
      end(reporter);
      await Bun.sleep(60);
      expect(ran.filter(event => event === "PreToolUse")).toEqual([]);
    }
  });
});

/** omp's side of the extension API as far as this extension uses it: handlers by event name. */
function ompHost() {
  const handlers = new Map<string, (event: unknown, ctx: unknown) => unknown>();
  const pi = { on: (name: string, handler: (event: unknown, ctx: unknown) => unknown) => handlers.set(name, handler) };
  const fire = (event: { type: string; [field: string]: unknown }, ctx: unknown) => handlers.get(event.type)?.(event, ctx);
  return { pi, fire, handlers };
}

function session(id: string, extra: Record<string, unknown> = {}) {
  return { ...tui, sessionManager: { getSessionId: () => id }, ...extra };
}

describe("in omp", () => {
  const root = session(common.session_id);

  test("a turn with an approval and an ask reaches the hook in order, as the hook's events", async () => {
    const { pi, fire } = ompHost();
    const ran: Hook[] = [];
    const reporter = register(pi, {}, async h => { ran.push(h); }, common.pid);
    fire({ type: "session_start" }, root);
    fire({ type: "agent_start" }, root);
    fire({ type: "tool_execution_start", toolCallId: "c1", toolName: "bash", args: { command: "git push" } }, root);
    fire({ type: "tool_approval_requested", sessionId: "s", toolCallId: "c1", toolName: "bash",
           approvalMode: "always-ask" }, root);
    fire({ type: "tool_approval_resolved", sessionId: "s", toolCallId: "c1", toolName: "bash", approved: true }, root);
    fire({ type: "tool_execution_end", toolCallId: "c1", toolName: "bash", result: "", isError: false }, root);
    fire({ type: "tool_execution_start", toolCallId: "c2", toolName: "ask",
           args: { questions: [{ id: "q", question: "Ship it?", options: [{ label: "yes" }] }] } }, root);
    fire({ type: "tool_execution_end", toolCallId: "c2", toolName: "ask", result: "", isError: false }, root);
    fire({ type: "agent_end", messages: [] }, root);
    await reporter.drained();
    expect(ran.map(h => h.event)).toEqual([
      "SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse", "PostToolUse",
      "Notification", "PostToolUse", "Stop"]);
    expect(ran[3].payload).toEqual({ ...common, tool_use_id: "c1", tool_name: "bash",
                                     tool_input: { command: "git push" } });
  });

  test("a subagent's copy, a print run and a nested omp report nothing", async () => {
    for (const [ctx, env] of [[session("child", { hasUI: false }), {}], [session("p", { mode: "print" }), {}],
                              [root, { OMPCODE: "1" }]] as const) {
      const { pi, fire } = ompHost();
      const ran: Hook[] = [];
      const reporter = register(pi, env, async h => { ran.push(h); }, common.pid);
      fire({ type: "session_start" }, ctx);
      fire({ type: "agent_start" }, ctx);
      fire({ type: "agent_end", messages: [] }, ctx);
      await reporter.drained();
      expect(ran).toEqual([]);
    }
  });

  test("a switch reports the new session under its own id", async () => {
    const { pi, fire } = ompHost();
    const ran: Hook[] = [];
    const reporter = register(pi, {}, async h => { ran.push(h); }, common.pid);
    fire({ type: "session_start" }, root);
    fire({ type: "session_switch", reason: "new", previousSessionFile: undefined }, session("019a0c5f-0000-7000-8000-000000000001"));
    fire({ type: "agent_start" }, session("019a0c5f-0000-7000-8000-000000000001"));
    await reporter.drained();
    expect(ran.map(h => [h.event, h.payload.session_id])).toEqual([
      ["SessionStart", common.session_id], ["SessionStart", "019a0c5f-0000-7000-8000-000000000001"],
      ["UserPromptSubmit", "019a0c5f-0000-7000-8000-000000000001"]]);
  });

  test("a switch drops the reports still waiting for the session before", async () => {
    const { pi, fire } = ompHost();
    const { log, run, finishOne } = heldRunner();
    register(pi, {}, run, common.pid);
    fire({ type: "session_start" }, root);
    fire({ type: "agent_start" }, root);
    fire({ type: "tool_execution_start", toolCallId: "c1", toolName: "bash", args: { command: "ls" } }, root);
    fire({ type: "session_switch", reason: "new", previousSessionFile: undefined }, session("019a0c5f-0000-7000-8000-000000000001"));
    await finishOne();
    await finishOne();
    expect(log).toEqual(["start SessionStart", "end SessionStart", "start SessionStart", "end SessionStart"]);
  });

  test("omp waits on the shutdown handler until the session's end has reached the hook", async () => {
    const { pi, fire } = ompHost();
    const { log, run, finishOne } = heldRunner();
    register(pi, {}, run, common.pid);
    fire({ type: "session_start" }, root);
    const shutdown = fire({ type: "session_shutdown" }, root) as Promise<void>;
    let over = false;
    void shutdown.then(() => { over = true; });
    await finishOne();
    expect(over).toBe(false);
    await finishOne();
    expect(over).toBe(true);
    expect(log).toEqual(["start SessionStart", "end SessionStart", "start SessionEnd", "end SessionEnd"]);
  });

  test("the session's end goes next, past what still waits, since it clears all of that", async () => {
    const { pi, fire } = ompHost();
    const { log, run, finishOne } = heldRunner();
    register(pi, {}, run, common.pid);
    fire({ type: "session_start" }, root);
    fire({ type: "agent_start" }, root);
    fire({ type: "agent_end", messages: [] }, root);
    void fire({ type: "session_shutdown" }, root);
    await finishOne();
    await finishOne();
    expect(log).toEqual(["start SessionStart", "end SessionStart", "start SessionEnd", "end SessionEnd"]);
  });

  test("a handler that meets something it cannot read returns quietly", () => {
    const { pi, handlers } = ompHost();
    register(pi, {}, async () => {}, common.pid);
    const throwing = { ...tui, sessionManager: { getSessionId: () => { throw new Error("disposed"); } } };
    for (const [name, handler] of handlers) expect(() => handler({ type: name }, throwing)).not.toThrow();
  });
});

describe("the child", () => {
  const scratch = realpathSync(mkdtempSync(join(tmpdir(), "omp-child-")));
  afterAll(() => rmSync(scratch, { recursive: true, force: true }));
  const python = Bun.which("python3")!;

  /** A stand-in for the state hook that records how it was run. */
  function recordingHandler(name: string, body = "") {
    const handler = join(scratch, name);
    const seen = join(scratch, name + ".seen");
    writeFileSync(handler, [
      "import json, os, sys",
      body,
      `json.dump({"argv": sys.argv[1:], "stdin": sys.stdin.read(), "cwd": os.getcwd(),`,
      `           "env": sorted(k for k in os.environ if k not in ("__CF_USER_TEXT_ENCODING", "LC_CTYPE"))},`,
      `          open(${JSON.stringify(seen)}, "w"))`,
    ].join("\n"));
    return { handler, seen };
  }

  test("runs the hook for omp with the payload on stdin and nothing of omp's environment but what it needs", async () => {
    const { handler, seen } = recordingHandler("emit.py");
    const env = childEnv({ HOME: "/Users/x", PATH: "/usr/bin:/bin", TMUX: "/tmp/tmux-1/default,1,0",
                           ANTHROPIC_API_KEY: "secret", OMPCODE: undefined });
    await spawnHandler(python, handler, env)({ event: "Stop", payload: common });
    const got = JSON.parse(readFileSync(seen, "utf8"));
    expect(got.argv).toEqual(["Stop", "--agent", "omp"]);
    expect(JSON.parse(got.stdin)).toEqual(common);
    expect(got.cwd).toBe(scratch);
    expect(got.env).toEqual(["HOME", "PATH", "TMUX"]);
  });

  test("passes the terminal's name when omp has one", () => {
    expect(childEnv({ HOME: "/Users/x", PATH: "/bin", TTY: "/dev/ttys004", SHELL: "/bin/zsh" }))
      .toEqual({ HOME: "/Users/x", PATH: "/bin", TTY: "/dev/ttys004" });
  });

  test("a hook that hangs is killed at its deadline, and the next report goes on", async () => {
    const { handler } = recordingHandler("hang.py", "import time; time.sleep(30)");
    const began = Date.now();
    await spawnHandler(python, handler, childEnv({ PATH: "/usr/bin:/bin" }), 300)({ event: "Stop", payload: common });
    expect(Date.now() - began).toBeLessThan(2000);
  });

  test("a hook given the time a loaded machine takes is not killed", async () => {
    const { handler, seen } = recordingHandler("slow.py", "import time; time.sleep(1.2)");
    await spawnHandler(python, handler, childEnv({ PATH: "/usr/bin:/bin" }))({ event: "Stop", payload: common });
    expect(JSON.parse(readFileSync(seen, "utf8")).argv).toEqual(["Stop", "--agent", "omp"]);
  });

  test("a python that is not there costs the report and nothing else", async () => {
    const { handler } = recordingHandler("never.py");
    await spawnHandler(join(scratch, "no-python"), handler, {})({ event: "Stop", payload: common });
  });
});
