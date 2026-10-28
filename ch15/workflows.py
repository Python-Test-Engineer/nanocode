"""workflows.py - four shapes for a parent agent and its subagents.

Chapter 15 gives the agent one new verb: `spawn(task) -> str`, "run a subagent to
completion and give me its answer". That verb is enough to build every multi-agent
arrangement people give names to, and this file is the four that are worth
knowing. Each is a pure function over `spawn`, so:

    * it works with a real agent   (`agent._spawn_subagent`)
    * it works with a fake one     (`lambda task: f"echo {task}"`)
    * it has no idea whether spawn is a thread, a process or a network call
    * it can be tested without a model, a key or a network

WHICH SHAPE TO USE

    fan-out      N independent pieces, one subagent each, answers side by side.
                 "Review these six files." The default. Parallel and simple.
    pipeline     one piece of work, several stages, each stage's output is the
                 next stage's input. Sequential by nature: draft -> edit -> test.
    map-reduce   fan-out, then one more subagent merges the answers. For when N
                 views have to become one decision.
    critic loop  one writer, one reviewer, N rounds. Expensive, and the only one
                 here that improves an answer instead of collecting them.

THE RULE ALL FOUR OBEY
  A subagent cannot ask a question, so every task this file builds must carry
  everything a stranger needs: the goal, the inputs, and the shape of the answer
  wanted. That is why the strings below are so explicit. Delegation does not
  remove work; it moves the work from "solving it" to "describing it".

WHAT THIS FILE DELIBERATELY DOES NOT DO
  No queues, no retries, no memory between stages, no depth limit. Those are
  systems. This is a page of functions you can read in one sitting and replace
  with your own the moment your workflow does not fit one of the four.
"""

from concurrent.futures import ThreadPoolExecutor


def _with_input(instruction, text):
    """One consistent way to hand a stage its input, so prompts stay comparable."""
    return f"{instruction.strip()}\n\n--- INPUT ---\n{text}\n--- END INPUT ---"


def fan_out(spawn, tasks, workers=4):
    """Map: one subagent per task, all at once. Returns answers in input order.

    Use when the tasks are genuinely independent - different files, different
    pages, different questions. If task B needs task A's answer, this is the
    wrong shape and you want `pipeline`.

    Parallelism is bounded by `workers` so a list of 50 tasks starts 4 at a time
    instead of 50. Results are ordered by task, not by finish time, because the
    caller almost always wants to zip them back up with the inputs.
    """
    tasks = list(tasks)
    if not tasks:
        return []
    if len(tasks) == 1:
        return [spawn(tasks[0])]
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(tasks)))) as pool:
        return list(pool.map(spawn, tasks))


def pipeline(spawn, task, stages):
    """Chain: each stage's answer becomes the next stage's input.

    `stages` is a list of instructions, in order. The first receives the task, the
    last one's answer is the result, and every stage in between is a fresh
    subagent - so a long chain does not fill one context window with everything
    that was said. The cost is the same as it looks: N stages, N calls, one after
    another, no way to parallelise what is inherently sequential.
    """
    text = task
    for index, instruction in enumerate(stages, start=1):
        text = spawn(_with_input(f"Stage {index} of {len(stages)}. {instruction}", text))
    return text


def map_reduce(spawn, tasks, reduce_task, workers=4):
    """Fan out, then merge: N subagents answer, one more subagent decides.

    The reduce prompt sees every answer labelled with its task, so it can compare
    them; it does not see the subagents' conversations. If the answers are long,
    reduce in two levels (map, reduce, reduce) rather than sending all of them to
    one prompt - the same trade-off as any reduce step.
    """
    tasks = list(tasks)
    answers = fan_out(spawn, tasks, workers=workers)
    sections = [
        f"### Task {index}\n{task}\n\n### Answer {index}\n{answer}"
        for index, (task, answer) in enumerate(zip(tasks, answers), start=1)
    ]
    return spawn(f"{reduce_task.strip()}\n\n" + "\n\n".join(sections))


def critic_loop(spawn, task, rounds=2):
    """Write, critique, revise - `rounds` times. Returns the final draft.

    The reviewer is a subagent with a fresh context, which is the point: it has
    not already decided the draft is good. The writer, too, is a fresh subagent
    each round, so "revise" means revise from the text rather than from having
    written it.

    Two rounds is usually one more than the improvement is worth. Measure before
    raising it: each round is two more model calls, and round three mostly
    rewrites round two.
    """
    draft = spawn(_with_input(
        "Write a first draft that answers the task. Be concrete; no preamble.",
        task,
    ))
    for _round in range(max(0, rounds)):
        critique = spawn(
            f"Critique the draft against the task. List only concrete problems "
            f"(missing fact, wrong claim, unclear step), most important first.\n\n"
            f"--- TASK ---\n{task}\n\n--- DRAFT ---\n{draft}\n--- END DRAFT ---"
        )
        draft = spawn(
            f"Revise the draft to fix the problems in the critique. Keep what is "
            f"already right. Return only the revised draft.\n\n"
            f"--- DRAFT ---\n{draft}\n\n--- CRITIQUE ---\n{critique}"
        )
    return draft


# (name, one line, when to reach for it) - read by the demo's --list and by the
# chapter's table, so the prose and the code cannot drift apart.
PATTERNS = (
    ("fan-out", "one subagent per task, in parallel",
     "the tasks do not depend on each other"),
    ("pipeline", "each stage feeds the next, one at a time",
     "the work is a sequence: draft -> review -> test"),
    ("map-reduce", "fan out, then one subagent merges the answers",
     "many views must become one decision"),
    ("critic-loop", "write, critique, revise, repeat",
     "the answer has to get better, not just arrive"),
)


def describe():
    """PATTERNS as a printable block, used by `demo_workflows.py --list`."""
    width = max(len(name) for name, _, _ in PATTERNS)
    lines = []
    for name, what, when in PATTERNS:
        lines.append(f"  {name.ljust(width)}  {what}")
        lines.append(f"  {' ' * width}  when: {when}")
    return "\n".join(lines)
