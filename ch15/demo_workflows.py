"""demo_workflows.py - watch subagents work, with no API key and no network.

    uv run ch15/demo_workflows.py              # all four patterns
    uv run ch15/demo_workflows.py fanout       # just one
    uv run ch15/demo_workflows.py pipeline critic
    uv run ch15/demo_workflows.py --list       # what the patterns are for
    uv run ch15/demo_workflows.py --live "audit ch15/tools.py and report"  # real brain

WHY OFFLINE
  A demo you cannot run is not a demo. This file swaps the brain for `DemoBrain`
  below - a stand-in that answers from the task's own words - and drives the REAL
  Agent, RunSubagent tool, sandbox and hook bus. Every `[sub1]` line you see was
  printed by a real nested `_agentic_loop()` running a real tool. Only the model
  is faked, which is the part that needs a key, a network and money.

  `--live` is the same wiring with a real provider: no fake brain, no canned
  answers, and it needs the usual .env. Use it to see the thing you just watched
  with the training wheels on.

WHAT TO LOOK FOR
  1. each subagent gets a label (`[sub1]`, `[sub2]` ...) on every line it prints
  2. those lines interleave under fan-out - the children really do run at once
  3. the parent prints one answer per child, never the child's conversation
  4. `⟡ hook:subagent_start` / `subagent_end` bracket each child on the parent's
     bus; the child's own tool calls never appear there
"""

import os
import sys
import time

from rich.text import Text

import hooks
import sandbox
import sounds
import ui
import workflows
from llm import Brain, Thought, ToolCall
from nanocode import Agent
from tools import tools as all_tools


# --- The stand-in brain ------------------------------------------------------

class DemoBrain(Brain):
    """A brain with no network: it answers from a table of canned replies.

    It is deterministic on purpose - a demo that varies is a demo you cannot
    compare across runs - and it still exercises every real seam: the tool table,
    `context.spawn`, the nested loop, the hook bus and the UI labels.

    A real model would decide these things by reading the task. This one looks for
    a keyword, which is enough to show the *shape* of a delegation: who runs what,
    in which order, and what the parent ends up holding.
    """

    model = "demo-brain"
    context_limit = 200_000

    def __init__(self, memory=None, tools=None):
        super().__init__(memory, tools)
        self.calls = 0
        self.task = None  # a child's original task, remembered across tool results

    # -- the one method the agent knows about --

    def think(self, conversation):
        if self._is_subagent():
            if self.task is None:
                self.task = _last_user_text(conversation)
            # A real model waits a second or three. Sleeping a fraction here keeps
            # the trace honest about *concurrency*: with four children in flight,
            # their lines interleave, which is the thing a parallel fan-out is for.
            time.sleep(0.15)
            # First move: look at something real, so the nested loop does actual
            # work. Second move: report. That is a two-step agent, in miniature.
            if not _has_tool_result(conversation):
                return self._tool("list_files", {"path": "."})
            # Answer the TASK, not the tool output - a real model has both, but
            # the task is what it was asked. (This is the classic subagent bug:
            # reading the last message and answering the file listing instead.)
            return self._say(_answer(self.task))

        prompt = _last_user_text(conversation)

        # The parent's only orchestrated turn: it fans out through the real tool,
        # which is what puts `run_subagents` through `_execute_tool` and
        # `Agent._spawn_many` instead of calling the workflow helper directly.
        if "AUDIT THE CHAPTER" in prompt and not _has_tool_result(conversation):
            return self._tool("run_subagents", {"tasks": list(AUDIT_TASKS)})

        # After the tool result, the parent merges. It sees the children's
        # answers as one string - exactly what a real parent model would see.
        return self._say(_merge_audit(prompt))

    # -- helpers --

    def _is_subagent(self):
        return "You are a subagent" in (self.system or "")

    def _say(self, text):
        return Thought(text=text, raw_content=[{"type": "text", "text": text}])

    def _tool(self, name, args):
        self.calls += 1
        call_id = f"demo_{self.calls}"
        block = {"type": "tool_use", "id": call_id, "name": name, "input": args}
        return Thought(text=None, tool_calls=[ToolCall(call_id, name, args)], raw_content=[block])


AUDIT_TASKS = (
    "SECURITY review: read ch15/tools.py and say what a model could do with "
    "run_command, and what the sandbox does and does not stop. Three bullets.",
    "TEST review: read ch15/nanocode.py and list which new subagent behaviours "
    "the test suite does not yet cover. Three bullets.",
    "LAYOUT review: explain the module layout of ch15/ - which file holds what "
    "and which imports which - for a reader seeing it for the first time.",
)

SECURITY = """- Tool arguments are plain keyword args; a missing one is an error string, never a crash.
- `run_command` is a real shell: the fence reads redirects and obvious mutators, nothing more.
- The sandbox bounds file tools and best-effort shell writes. It is not a container."""

TESTS = """- No test yet that a child cannot see the parent's conversation.
- No test that a parallel fan-out returns answers in task order.
- No test that a failing child leaves the parent's turn alive."""

LAYOUT = """- `tools.py` owns capability; `run_subagent` only calls `context.spawn`.
- `nanocode.py` owns policy: it builds the child, filters its menu, gives it a bus.
- `workflows.py` owns arrangement; it is pure functions over `spawn`."""


def _answer(prompt):
    """Route a task to a canned answer, the way a model would route on meaning."""
    text = prompt.lower()
    if "security" in text:
        return SECURITY
    if "test review" in text or "test coverage" in text:
        return TESTS
    if "layout" in text:
        return LAYOUT

    # the map-reduce demo. `merge` first: the reduce prompt quotes all three map
    # tasks, so any keyword from those tasks is also in *its* text.
    if "merge" in text:
        return ("MERGED\n1. Show the labels: the `[subN]` prefix is the demo.\n"
                "2. Keep each child's task self-contained - no shared context.\n"
                "3. The parent holds one result per child, not the transcript.\n"
                "4. Cost is one summary, not N conversations.")
    if "must show" in text:
        return ("- Show the LABELS, not just the answer: `[sub1]` on a line is the "
                "proof a child ran, and the only proof a user ever gets.")
    if "must not do" in text:
        return ("- Must not pretend the children share context: every task is written "
                "as if for a stranger, because it is.")
    if "one number" in text:
        return ("- 3 subagents, 1 tool result: the parent's context grew by the "
                "summary, not by three transcripts.")

    # the pipeline / critic demos. Order matters: a later stage quotes the earlier
    # instruction ("write the first draft FROM THIS OUTLINE"), so the most specific
    # verb has to be tested first. A real model reads intent; this reads keywords.
    if "first draft" in text:
        return ("DRAFT (about 340 words, one section per beat)\n"
                "A subagent is an Agent with its own context. It has a brain, a "
                "conversation, a tool menu and a sandbox - all fresh. The parent "
                "asks for it with one tool call and receives one answer.")
    if "tighten" in text:
        return ("FINAL (120 words)\n"
                "A subagent is an Agent, not a process: its own context, its own "
                "tool menu, the same loop one stack frame deeper. The parent asks "
                "with `run_subagent` and gets one answer back. Four arrangements "
                "cover most work: fan-out, pipeline, map-reduce, critic loop.")
    if "outline" in text:
        return ("OUTLINE\n1. A subagent is an Agent, not a process\n"
                "2. The tool only asks; the agent builds\n"
                "3. Four arrangements, one verb\n4. Run the offline demo")
    if "revise" in text:  # before "critique": the revise prompt quotes the critique
        return ("REVISED\nSubagents are Agents with their own context. Use "
                "`run_subagent` to delegate one task, `run_subagents` to fan out; "
                "try `uv run ch15/demo_workflows.py`.")
    if "critique" in text:
        return ("CRITIQUE\n- opens with a definition nobody asked for\n"
                "- claims 'four patterns' without naming them\n- no command to run")
    return "ANSWER\n" + _input_block(prompt)[:300]


def _input_block(prompt):
    """The text between the INPUT markers, i.e. what the previous stage produced."""
    if "--- INPUT ---" in prompt and "--- END INPUT ---" in prompt:
        return prompt.split("--- INPUT ---", 1)[1].split("--- END INPUT ---", 1)[0].strip()
    return prompt


def _merge_audit(prompt):
    # RunSubagents labels each answer "Subagent N:"; count those, not the answers.
    count = sum(1 for line in prompt.splitlines() if line.startswith("Subagent "))
    return (f"## Audit summary\n\n{count} reviewers reported. Themes, in one line each:\n\n"
            f"- capability is fenced at the tool, not in the prompt\n"
            f"- the tests to add are about isolation, not about answers\n"
            f"- the layout has one rule: capability, policy, arrangement.\n\n"
            f"(The child answers arrived as a single tool result; their conversations "
            f"never entered this one.)")


def _last_user_text(conversation):
    """The most recent user message as text, whatever shape it arrived in."""
    for message in reversed(conversation):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        parts = []
        for block in content or []:
            if isinstance(block, dict):
                if block.get("type") == "tool_result":
                    parts.append(str(block.get("content", "")))
                elif block.get("type") == "text":
                    parts.append(block.get("text", ""))
        if parts:
            return "\n".join(parts)
    return ""


def _has_tool_result(conversation):
    for message in reversed(conversation):
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_result" for block in content
        ):
            return True
    return False


# --- Wiring ------------------------------------------------------------------

def new_agent(brain=None):
    """A real Agent with the demo brain, in PLAN mode: nothing here writes."""
    agent = Agent(
        brain=brain or DemoBrain(),
        tools=all_tools,
        memory=None,
        mode="plan",
        brain_name="demo",
    )
    hooks.install(agent.hooks)   # ⟡ lines: the loop, made visible
    sounds.install(agent.hooks)  # silent unless NANOCODE_SOUND is set
    sandbox.install(agent.hooks)
    return agent


def section(title, what):
    ui.blank()
    ui.print(Text(f"── {title}", style="bold bright_cyan"))
    ui.print(Text(f"   {what}", style="grey58"))
    ui.blank()


# --- The four patterns -------------------------------------------------------

def run_fanout():
    """The agent decides to fan out, via the tool, exactly as a real model would."""
    section("fan-out · the agent delegates through the tool",
            "run_subagents -> Agent._spawn_many -> 3 threads -> one merged answer")
    agent = new_agent()
    answer = agent.handle_input(
        "AUDIT THE CHAPTER: review security, tests and layout of ch15, then merge "
        "the reviews into a short summary."
    )
    ui.answer(answer)


def run_pipeline():
    """Sequential: no parallelism possible, every stage needs the last answer."""
    section("pipeline · each stage's answer is the next stage's input",
            "outline -> draft -> tighten, three subagents, one at a time")
    agent = new_agent()
    answer = workflows.pipeline(
        agent._spawn_subagent,
        "Write a 120-word introduction to chapter 15 for a reader who has read ch14.",
        stages=(
            "Outline the introduction in four numbered beats.",
            "Write the first draft from this outline.",
            "Tighten the draft: cut every sentence that does not add a fact.",
        ),
    )
    ui.answer(answer)


def run_mapreduce():
    """Parallel collection, then a single decision made by one more subagent."""
    section("map-reduce · three opinions, one decision",
            "3 subagents in parallel, then a 4th that only sees their answers")
    agent = new_agent()
    tasks = (
        "Name one thing the ch15 demo must show, in one line. Argue for it.",
        "Name one thing the ch15 demo must NOT do, in one line. Argue for it.",
        "Name the one number a reader should take away from ch15. One line.",
    )
    answer = workflows.map_reduce(
        agent._spawn_subagent,
        tasks,
        "Merge these three positions into a numbered list of at most four points. "
        "Drop anything they agree is unimportant.",
    )
    ui.answer(answer)


def run_critic():
    """The only pattern that improves an answer rather than collecting one."""
    section("critic loop · write, critique, revise",
            "two rounds: each critique and each revision is a fresh subagent")
    agent = new_agent()
    answer = workflows.critic_loop(
        agent._spawn_subagent,
        "Explain, in three sentences, why a subagent does not need its own process.",
        rounds=2,
    )
    ui.answer(answer)


RUNNERS = {
    "fanout": run_fanout,
    "pipeline": run_pipeline,
    "mapreduce": run_mapreduce,
    "critic": run_critic,
}


# --- Live mode ---------------------------------------------------------------

def run_live(task):
    """The same agent with a real provider: no fake brain, real answers.

    This is deliberately the ordinary interactive wiring from `nanocode.main()`,
    minus the REPL: one `handle_input` call, with subagents available to the
    model. If it decides not to delegate, that is an answer too - a subagent is
    a tool the model may ignore.
    """
    from llm import BRAINS
    from nanocode import Memory
    from tools import tool_definitions

    brain_name = os.getenv("NANOCODE_BRAIN", "openrouter")
    memory = Memory()
    try:
        brain = BRAINS[brain_name](memory=memory, tools=tool_definitions(all_tools))
    except (KeyError, ValueError) as error:
        ui.error(f"Cannot start brain '{brain_name}': {error}")
        ui.info("Set OPENROUTER_API_KEY in .env, or run without --live.")
        return 1

    agent = Agent(brain=brain, tools=all_tools, memory=memory, mode="act",
                  brain_name=brain_name, sandbox=sandbox.Sandbox())
    hooks.install(agent.hooks)
    sounds.install(agent.hooks)
    sandbox.install(agent.hooks)
    ui.banner(brain=brain_name, model=getattr(brain, "model", "?"), mode="act",
              version="ch15", tool_count=len(agent.tools))
    agent.hooks.emit("session_start", brain=brain_name, model=agent.brain.model, mode="act")
    started = time.monotonic()
    ui.answer(agent.handle_input(task))
    ui.info(f"done in {time.monotonic() - started:.1f}s · "
            f"{agent.subagents_spawned} subagent(s)")
    return 0


# --- Entry point -------------------------------------------------------------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--list" in argv or "-l" in argv:
        ui.configure()
        ui.print(Text("ch15 patterns", style="bold bright_cyan"))
        ui.print(workflows.describe())
        return 0

    if "--live" in argv:
        index = argv.index("--live")
        task = " ".join(argv[index + 1:]).strip()
        if not task:
            ui.error("--live needs a task, e.g. --live \"audit ch15/tools.py\"")
            return 2
        ui.configure()
        return run_live(task)

    if "--help" in argv or "-h" in argv:
        ui.print(__doc__)
        return 0

    wanted = [name for name in argv if not name.startswith("-")] or list(RUNNERS)
    unknown = [name for name in wanted if name not in RUNNERS]
    if unknown:
        ui.error(f"unknown workflow {unknown}. Choose from: {', '.join(RUNNERS)}, or --live")
        return 2

    ui.configure()
    ui.print(Text("⚡ Nanocode ch15 · subagents offline", style="bold bright_cyan"))
    ui.print(Text("   the real Agent, tool and hook code; only the model is scripted",
                  style="grey58"))
    for name in wanted:
        RUNNERS[name]()
    ui.blank()
    ui.print(Text("   the same thing with a real brain:  "
                  "uv run ch15/demo_workflows.py --live \"...\"", style="grey46"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
