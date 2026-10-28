"""Tests for Nanocode v1.0 (Chapter 15 - subagents and workflow patterns).

Chapter 15 is chapter 14 plus delegation: `run_subagent` / `run_subagents` in
tools.py, `Agent._spawn_subagent` / `_spawn_many` in nanocode.py, and the four
arrangements in workflows.py. Everything above the chapter-15 section is the
chapter-14 suite, unchanged.

Two things are deliberately tested here rather than in the demo: that a child
gets a FRESH sandbox and hook bus (sharing either is the classic bug), and that
`_spawn_many` really overlaps its children - the barrier test fails in five
seconds if it ever goes sequential.
"""

import os
import tempfile

import sandbox
import sounds
import ui
import workflows
from hooks import EVENTS, Hooks
from nanocode import (
    Agent, AgentStop, Thought, ToolCall, Memory, ToolContext,
    ReadFile, WriteFile, WritePlan, ListFiles, SearchCodebase, SaveMemory, RunCommand, SearchWeb,
    RunSubagent, RunSubagents,
    EditFile, BRAINS, tools, get_tool, tool_definitions, Sandbox,
)


# --- Fake Brain for Testing ---

class FakeBrain:
    """Fake brain for testing - returns predictable responses."""
    context_limit = 200_000
    last_input_tokens = 0

    def __init__(self, responses=None, memory=None, tools=None):
        self.memory = memory
        self.tools = tools or []
        self.responses = responses or [Thought(text="Fake response", raw_content=[{"type": "text", "text": "Fake response"}])]
        self.call_count = 0
        self.last_conversation = None

    def think(self, conversation):
        self.last_conversation = list(conversation)
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        return Thought(text="No more responses", raw_content=[{"type": "text", "text": "No more responses"}])


# --- Chapter 11: SearchWeb Tool Tests ---

def test_search_web_tool_exists():
    """Verify SearchWeb class exists with required attributes."""
    tool = SearchWeb()
    assert tool.name == "search_web"
    assert tool.description is not None
    assert tool.input_schema is not None
    assert "query" in tool.input_schema["properties"]


def test_search_web_in_tools_list():
    """Verify SearchWeb is registered in the tools list."""
    tool_names = [t.name for t in tools]
    assert "search_web" in tool_names


def test_search_web_can_be_found():
    """Verify get_tool can find search_web."""
    tool = get_tool(tools, "search_web")
    assert tool is not None
    assert tool.name == "search_web"


def test_search_web_in_tool_definitions():
    """Verify search_web appears in tool definitions for API."""
    definitions = tool_definitions(tools)
    names = [d["name"] for d in definitions]
    assert "search_web" in names


def test_search_web_execute_success(monkeypatch):
    """Verify SearchWeb.execute() returns formatted results."""
    fake_results = [
        {"title": "Python 3.13", "href": "https://python.org", "body": "Latest release"},
    ]
    monkeypatch.setattr("nanocode.DDGS", lambda: type("FakeDDGS", (), {"text": lambda self, q, max_results=3: fake_results})())
    tool = SearchWeb()
    context = ToolContext()
    result = tool.execute(context, "latest python version")
    assert "Python 3.13" in result
    assert "https://python.org" in result


def test_search_web_execute_no_results(monkeypatch):
    """Verify SearchWeb.execute() handles empty results."""
    monkeypatch.setattr("nanocode.DDGS", lambda: type("FakeDDGS", (), {"text": lambda self, q, max_results=3: []})())
    tool = SearchWeb()
    context = ToolContext()
    result = tool.execute(context, "impossible query xyz")
    assert "No results found" in result


def test_search_web_execute_error(monkeypatch):
    """Verify SearchWeb.execute() handles errors gracefully."""
    def raise_error():
        raise RuntimeError("Network down")
    monkeypatch.setattr("nanocode.DDGS", lambda: type("FakeDDGS", (), {"text": lambda self, q, max_results=3: raise_error()})())
    tool = SearchWeb()
    context = ToolContext()
    result = tool.execute(context, "test query")
    assert "Error" in result


# --- Previous Chapter Tests (Cumulative) ---

def test_handle_input_returns_string():
    """Basic test: handle_input returns a string."""
    agent = Agent(brain=FakeBrain(), tools=tools)
    result = agent.handle_input("Hello")
    assert isinstance(result, str)


def test_quit_command_raises_agent_stop():
    """Verify /q raises AgentStop."""
    agent = Agent(brain=FakeBrain(), tools=tools)
    try:
        agent.handle_input("/q")
        assert False, "Should have raised AgentStop"
    except AgentStop:
        pass


def test_messages_accumulate():
    """Verify conversation history accumulates."""
    agent = Agent(brain=FakeBrain(), tools=tools)
    agent.handle_input("First message")
    agent.handle_input("Second message")
    # Should have 4 messages: user, assistant, user, assistant
    assert len(agent.conversation) == 4


def test_brains_registry_has_expected_providers():
    """Verify BRAINS registry contains all providers."""
    assert "claude" in BRAINS
    assert "deepseek" in BRAINS
    assert "ollama" in BRAINS


def test_read_file_adds_line_numbers():
    """Verify ReadFile prefixes each line with line numbers."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("line one\nline two\nline three\n")
        temp_path = f.name

    try:
        tool = ReadFile()
        context = ToolContext()
        result = tool.execute(context, temp_path)
        assert "1 | line one" in result
        assert "2 | line two" in result
        assert "3 | line three" in result
    finally:
        os.unlink(temp_path)


def test_write_file_creates_file():
    """Verify WriteFile creates a file with content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.txt")
        tool = WriteFile()
        context = ToolContext()
        result = tool.execute(context, path, "hello world")

        assert os.path.exists(path)
        assert "Successfully wrote" in result
        with open(path) as f:
            assert f.read() == "hello world"


def test_plan_mode_hides_write_tools():
    """Verify plan mode removes write tools from brain's menu."""
    agent = Agent(brain=FakeBrain(), tools=tools, mode="plan")
    tool_names = [t["name"] for t in agent.brain.tools]
    assert "write_file" not in tool_names
    assert "edit_file" not in tool_names
    assert "run_command" not in tool_names
    assert "write_plan" in tool_names
    assert "read_file" in tool_names
    assert "search_web" in tool_names


def test_act_mode_shows_all_tools():
    """Verify act mode includes all tools in brain's menu."""
    agent = Agent(brain=FakeBrain(), tools=tools, mode="act")
    tool_names = [t["name"] for t in agent.brain.tools]
    assert "write_file" in tool_names
    assert "edit_file" in tool_names
    assert "run_command" in tool_names


def test_mode_switch_updates_brain_tools():
    """Verify switching mode updates the brain's tool menu."""
    agent = Agent(brain=FakeBrain(), tools=tools, mode="plan")
    plan_names = [t["name"] for t in agent.brain.tools]
    assert "write_file" not in plan_names
    agent.handle_input("/mode act")
    act_names = [t["name"] for t in agent.brain.tools]
    assert "write_file" in act_names


def test_write_plan_saves_file():
    """Verify WritePlan creates PLAN.md with content."""
    original_dir = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        try:
            tool = WritePlan()
            context = ToolContext()
            result = tool.execute(context, content="# My Plan")
            assert "Plan saved" in result
        finally:
            os.chdir(original_dir)


def test_write_file_writes_file():
    """Verify WriteFile creates a file with content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "test.py")
        tool = WriteFile()
        context = ToolContext()
        result = tool.execute(context, file_path, "print('hello')")
        assert "Successfully wrote" in result


def test_run_command_executes():
    """Verify RunCommand works."""
    tool = RunCommand()
    context = ToolContext()
    result = tool.execute(context, "echo hello")
    assert "hello" in result


def test_ollama_in_brains_registry():
    """Verify Ollama is in the BRAINS registry."""
    assert "ollama" in BRAINS


def test_version_is_1_0():
    """Verify version number is 1.0 in main()."""
    import nanocode
    import inspect
    source = inspect.getsource(nanocode.main)
    assert "v1.0" in source


# --- Context Compaction Tests ---

def test_compact_conversation_summarizes():
    """Verify compaction replaces conversation with summary."""
    summary = Thought(
        text="Summary of conversation",
        raw_content=[{"type": "text", "text": "Summary of conversation"}]
    )
    responses = [
        Thought(text="Response 1", raw_content=[{"type": "text", "text": "Response 1"}]),
        summary,
    ]
    brain = FakeBrain(responses=responses)
    brain.last_input_tokens = 200_000  # Over 75% threshold
    agent = Agent(brain=brain, tools=tools, mode="act")

    agent.handle_input("Do something")

    # After compaction, conversation should be short (summary + current response)
    assert len(agent.conversation) <= 4
    assert "Summary" in str(agent.conversation[0]["content"])


# --- Chapter 13: Sounds on the hook seam ---

CONFIG_OFF = {"mode": "off", "muted": False, "sounds": {"session_start": {"file": "x.wav"}}}
CONFIG_ON = {"mode": "media", "muted": False,
             "sounds": {"session_start": {"file": "C:\\Windows\\Media\\tada.wav"}}}


def test_sounds_session_start_defaults_to_tada():
    """The shipped sounds.json plays the Windows tada when the session starts."""
    spec = sounds.spec_for("session_start", sounds.load_config())
    assert spec is not None
    assert spec["file"].lower().endswith("tada.wav")


def test_sounds_off_by_default(monkeypatch):
    """Unset env and mode "off" means no sound: opt-in, never a surprise."""
    monkeypatch.delenv("NANOCODE_SOUND", raising=False)
    assert sounds.mode(CONFIG_OFF) == "off"
    assert sounds.enabled(CONFIG_OFF) is False


def test_sounds_env_selects_media(monkeypatch):
    """NANOCODE_SOUND=media turns playback on, overriding sounds.json."""
    monkeypatch.setenv("NANOCODE_SOUND", "media")
    assert sounds.mode(CONFIG_OFF) == "media"


def test_sounds_env_recognises_beep(monkeypatch):
    monkeypatch.setenv("NANOCODE_SOUND", "beep")
    assert sounds.mode(CONFIG_OFF) == "beep"


def test_sounds_env_override_wins_for_start(monkeypatch):
    """NANOCODE_SOUND_START re-points the session_start sound without a file edit."""
    monkeypatch.setenv("NANOCODE_SOUND_START", "D:\\custom\\startup.wav")
    spec = sounds.spec_for("session_start", sounds.load_config())
    assert spec is not None
    assert spec["file"] == "D:\\custom\\startup.wav"


def test_sounds_silent_when_disabled(monkeypatch):
    """play() makes no sound when sound is off, and never raises."""
    monkeypatch.delenv("NANOCODE_SOUND", raising=False)
    assert sounds.play("session_start", CONFIG_OFF) is False


def test_sounds_play_uses_winsound_media(monkeypatch):
    """In media mode with an existing WAV, play() calls winsound.PlaySound."""
    monkeypatch.setenv("NANOCODE_SOUND", "media")
    calls = []

    def fake_play_file(path):
        calls.append(path)
        return True

    monkeypatch.setattr(sounds, "_play_file", fake_play_file)
    assert sounds.play("session_start", CONFIG_ON) is True
    assert calls and calls[0].lower().endswith("tada.wav")


def test_sounds_missing_wav_falls_back_to_beep(monkeypatch):
    """A missing WAV degrades to a tone instead of going silent."""
    monkeypatch.setenv("NANOCODE_SOUND", "media")
    played = []
    monkeypatch.setattr(sounds, "_play_beep", lambda tones: played.append(tones) or True)
    config = {"mode": "media", "muted": False,
              "sounds": {"session_start": {"file": "C:\\nope\\missing.wav", "beep": [880, 120]}}}
    assert sounds.play("session_start", config) is True
    assert played == [[(880, 120)]]


def test_sounds_install_registers_a_handler_per_event():
    """install() subscribes one observer per configured event - and nothing else."""
    hooks = Hooks()
    sounds.install(hooks, sounds.load_config())
    assert hooks.handlers_for("session_start")          # the startup tada
    assert hooks.handlers_for("turn_end")
    assert hooks.handlers_for("before_think") == []     # not configured -> not wired


def test_sounds_handler_survives_a_broken_play(monkeypatch):
    """A failing sound is swallowed: an observer must never break a turn."""
    monkeypatch.setenv("NANOCODE_SOUND", "media")

    def boom(*_args, **_kwargs):
        raise RuntimeError("no audio device")

    monkeypatch.setattr(sounds, "_play_file", boom)
    hooks = Hooks()
    sounds.install(hooks, CONFIG_ON)
    hooks.emit("session_start")  # must not raise


def test_session_start_is_a_known_hook_event():
    """ch13 added session_start to the event list; emit() would reject it otherwise."""
    from hooks import EVENTS
    assert "session_start" in EVENTS


# --- Chapter 14: the sandbox ---

class FakeConsole:
    """Captures what ui would have printed, as plain text lines."""

    def __init__(self):
        self.lines = []

    def print(self, *objects, **kwargs):
        for obj in objects:
            self.lines.append(getattr(obj, "plain", str(obj)))

    def input(self, *args, **kwargs):  # ui.ask() should never be reached here
        raise EOFError


def _roots_pair():
    """Two sibling directories: one writable root, one definitely outside it."""
    base = tempfile.mkdtemp()
    root = os.path.join(base, "root")
    outside = os.path.join(base, "outside")
    os.makedirs(root)
    os.makedirs(outside)
    return root, outside


def test_sandbox_defaults_to_the_working_directory(monkeypatch):
    """No configuration means 'just in the folder': the rocks the agent started in."""
    monkeypatch.delenv("NANOCODE_SANDBOX", raising=False)
    monkeypatch.delenv("NANOCODE_SANDBOX_ROOTS", raising=False)
    policy = Sandbox()
    assert policy.enabled is True
    assert policy.roots == (policy.resolve("."),)
    assert policy.check("notes.txt") is None
    assert policy.check(os.path.join("..", "escape.txt")) is not None


def test_sandbox_allows_paths_inside_the_root():
    root, _outside = _roots_pair()
    policy = Sandbox(roots=[root])
    assert policy.check(os.path.join(root, "src", "app.py")) is None


def test_sandbox_refuses_paths_outside_the_root():
    root, outside = _roots_pair()
    policy = Sandbox(roots=[root])
    violation = policy.check(os.path.join(outside, "app.py"), tool="write_file")
    assert violation is not None
    assert violation.tool == "write_file"
    assert "FORBIDDEN" in violation.message()
    assert outside.lower() in violation.resolved.lower()


def test_sandbox_refuses_a_dotdot_escape_resolved_not_matched():
    """The check is on the resolved path: '../outside/x' cannot sneak past."""
    root, outside = _roots_pair()
    policy = Sandbox(roots=[root])
    sneaky = os.path.join(root, "..", "outside", "app.py")
    assert policy.check(sneaky) is not None


def test_sandbox_deny_beats_root():
    """A denied subtree is refused even though it sits inside a root."""
    root, _outside = _roots_pair()
    policy = Sandbox(roots=[root], deny=[os.path.join(root, ".git")])
    assert policy.check(os.path.join(root, ".git", "config")) is not None
    assert policy.check(os.path.join(root, "app.py")) is None


def test_sandbox_is_disarmed_in_plan_mode():
    """The fence follows the mode: PLAN has no write tools, so nothing to police."""
    policy = Sandbox()
    assert policy.arm("plan") is False
    assert policy.check(os.path.join("..", "anywhere.txt")) is None
    assert policy.arm("act") is True
    assert policy.check(os.path.join("..", "anywhere.txt")) is not None


def test_sandbox_can_be_switched_off(monkeypatch):
    """NANOCODE_SANDBOX=0 is the deliberate escape hatch."""
    monkeypatch.setenv("NANOCODE_SANDBOX", "0")
    policy = Sandbox()
    assert policy.enabled is False
    assert policy.armed is False
    assert policy.check(os.path.join("..", "anywhere.txt")) is None


def test_sandbox_roots_override_from_env(monkeypatch):
    """NANOCODE_SANDBOX_ROOTS widens the fence for one run, no file edit."""
    root, outside = _roots_pair()
    monkeypatch.setenv("NANOCODE_SANDBOX_ROOTS", root + os.pathsep + outside)
    policy = Sandbox()
    assert len(policy.roots) == 2
    assert policy.check(os.path.join(outside, "a.py")) is None


def test_sandbox_json_ships_fenced_to_the_folder():
    """The shipped sandbox.json is '.' with .git/.env denied - safe by default."""
    cfg = sandbox.load_config()
    assert cfg["enabled"] is True
    assert cfg["roots"] == ["."]
    assert ".git" in cfg["deny"]


def test_sandbox_denied_is_a_known_hook_event():
    assert sandbox.DENIED_EVENT in EVENTS


def test_write_file_outside_the_sandbox_is_refused():
    """The tool returns the refusal string and - the point - writes nothing."""
    root, outside = _roots_pair()
    target = os.path.join(outside, "doomed.txt")
    tool = WriteFile()
    result = tool.execute(ToolContext(sandbox=Sandbox(roots=[root])), target, "nope")
    assert "FORBIDDEN" in result
    assert not os.path.exists(target)


def test_write_file_inside_the_sandbox_still_writes():
    root, _outside = _roots_pair()
    target = os.path.join(root, "ok.txt")
    tool = WriteFile()
    result = tool.execute(ToolContext(sandbox=Sandbox(roots=[root])), target, "yes")
    assert "Successfully wrote" in result
    assert os.path.exists(target)


def test_edit_file_outside_the_sandbox_is_refused():
    root, outside = _roots_pair()
    target = os.path.join(outside, "app.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("old\n")
    tool = EditFile()
    result = tool.execute(ToolContext(sandbox=Sandbox(roots=[root])), target, "old", "new")
    assert "FORBIDDEN" in result
    with open(target, encoding="utf-8") as f:
        assert f.read() == "old\n"


def test_run_command_redirect_outside_the_sandbox_is_refused():
    root, outside = _roots_pair()
    target = os.path.join(outside, "pwned.txt")
    tool = RunCommand()
    result = tool.execute(ToolContext(sandbox=Sandbox(roots=[root])), f'echo hi > "{target}"')
    assert "FORBIDDEN" in result
    assert not os.path.exists(target)


def test_write_targets_reads_redirects_and_mutators():
    assert sandbox.write_targets('echo hi > "C:\\Windows\\x.txt"') == ["C:\\Windows\\x.txt"]
    assert sandbox.write_targets("rm -rf ../secrets") == ["../secrets"]
    assert sandbox.write_targets("pytest -q") == []


def test_refusal_emits_the_hook_event():
    """The refusal is an EVENT: tools do not print, they announce."""
    root, outside = _roots_pair()
    hooks = Hooks()
    seen = []
    hooks.on("sandbox_denied", lambda **payload: seen.append(payload))
    WriteFile().execute(
        ToolContext(sandbox=Sandbox(roots=[root]), hooks=hooks),
        os.path.join(outside, "doomed.txt"),
        "nope",
    )
    assert len(seen) == 1
    assert seen[0]["tool"] == "write_file"
    assert seen[0]["roots"] == (Sandbox(roots=[root]).roots[0],)
    assert "outside" in seen[0]["reason"]


def test_sandbox_install_prints_forbidden_and_plays_the_alarm(monkeypatch):
    """One handler, both channels: a red FORBIDDEN line and the warning sound."""
    fake = FakeConsole()
    monkeypatch.setattr(ui, "_console", fake)
    alarms = []
    monkeypatch.setattr(sounds, "alarm", lambda *a, **k: alarms.append(a) or True)

    hooks = Hooks()
    sandbox.install(hooks)
    hooks.emit("sandbox_denied", tool="write_file", path="../x.txt",
               reason="outside the writable roots", roots=("C:\\proj",))

    text = "\n".join(fake.lines)
    assert "FORBIDDEN" in text
    assert "../x.txt" in text
    assert alarms, "a refused write must make a noise"


def test_sandbox_install_survives_a_broken_alarm(monkeypatch):
    """A dead speaker must not turn a refusal into a traceback."""
    monkeypatch.setattr(sounds, "alarm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no audio")))
    hooks = Hooks()
    sandbox.install(hooks)
    hooks.emit("sandbox_denied", tool="write_file", path="x", reason="r", roots=())  # no raise


def test_agent_arms_the_sandbox_only_in_act_mode():
    plan = Agent(brain=FakeBrain(), tools=tools, mode="plan")
    assert plan.sandbox.armed is False
    plan.handle_input("/mode act")
    assert plan.sandbox.armed is True


def test_agent_refuses_a_write_outside_the_sandbox_end_to_end():
    """The whole chapter in one test: model asks, guard refuses, loop continues."""
    root, outside = _roots_pair()
    target = os.path.join(outside, "doomed.txt")
    responses = [
        Thought(
            text=None,
            tool_calls=[ToolCall("call_1", "write_file", {"path": target, "content": "nope"})],
            raw_content=[{"type": "tool_use", "id": "call_1", "name": "write_file",
                          "input": {"path": target, "content": "nope"}}],
        ),
        Thought(text="I could not write that file.", raw_content=[{"type": "text", "text": "I could not write that file."}]),
    ]
    agent = Agent(brain=FakeBrain(responses=responses), tools=tools, mode="act",
                  sandbox=Sandbox(roots=[root]))
    denied = []
    agent.hooks.on("sandbox_denied", lambda **payload: denied.append(payload))

    agent.handle_input("write outside the project")

    assert not os.path.exists(target)
    assert "FORBIDDEN" in str(agent.conversation)
    assert len(denied) == 1


def test_sounds_alarm_plays_even_when_sounds_are_off(monkeypatch):
    """The alarm is not decoration: mode "off" silences the tada, not FORBIDDEN."""
    cfg = {"mode": "off", "muted": False,
           "sounds": {"sandbox_denied": {"file": "C:\\Windows\\Media\\Windows Exclamation.wav",
                                          "beep": [300, 150]}}}
    played = []
    monkeypatch.setattr(sounds, "_play_spec", lambda spec, playback: played.append(playback) or True)
    monkeypatch.delenv("NANOCODE_SOUND_ALARM", raising=False)
    assert sounds.alarm("sandbox_denied", cfg) is True
    assert played == ["media"]


def test_sounds_alarm_can_be_silenced(monkeypatch):
    cfg = {"mode": "off", "muted": False,
           "sounds": {"sandbox_denied": {"file": "x.wav", "beep": [300, 150]}}}
    monkeypatch.setenv("NANOCODE_SOUND_ALARM", "0")
    assert sounds.alarm("sandbox_denied", cfg) is False


def test_sounds_install_leaves_the_alarm_to_the_sandbox():
    """No double play: install() skips alarm events, sandbox.install() owns them."""
    cfg = {"mode": "media", "muted": False,
           "sounds": {"sandbox_denied": {"file": "x.wav"}, "turn_end": {"file": "y.wav"}}}
    hooks = Hooks()
    sounds.install(hooks, cfg)
    assert hooks.handlers_for("sandbox_denied") == []
    assert hooks.handlers_for("turn_end")


def test_sounds_ship_a_warning_wav_for_denials():
    spec = sounds.spec_for("sandbox_denied", sounds.load_config())
    assert spec is not None
    assert spec["file"].lower().endswith("windows exclamation.wav")


# --- Chapter 14: reads are bounded too ---

def test_list_files_skips_cache_directories(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x", encoding="utf-8")

    out = ListFiles().execute(None, str(tmp_path))
    assert "app.py" in out
    assert "HEAD" not in out


def test_list_files_stops_at_the_entry_limit(monkeypatch, tmp_path):
    """`list_files C:\\` used to walk the whole drive; now it has a ceiling."""
    for i in range(30):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("NANOCODE_MAX_ENTRIES", "5")

    out = ListFiles().execute(None, str(tmp_path))
    assert "stopped after" in out
    assert "entry limit 5" in out
    assert out.count(".txt") <= 6  # the cap, not the 30 files that are there


def test_list_files_stops_on_the_clock(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOCODE_WALK_TIMEOUT", "0")
    out = ListFiles().execute(None, str(tmp_path))
    assert "time limit" in out


def test_search_codebase_stops_at_the_entry_limit(monkeypatch, tmp_path):
    for i in range(30):
        (tmp_path / f"f{i}.py").write_text(f"needle {i}\n", encoding="utf-8")
    monkeypatch.setenv("NANOCODE_MAX_ENTRIES", "5")

    out = SearchCodebase().execute(None, "needle", str(tmp_path))
    assert "stopped after" in out
    assert "entry limit 5" in out


def test_walk_budget_is_tunable(monkeypatch):
    monkeypatch.setenv("NANOCODE_MAX_ENTRIES", "7")
    monkeypatch.setenv("NANOCODE_WALK_TIMEOUT", "2.5")
    import tools as tools_module
    assert tools_module.walk_budget() == (7, 2.5)


# --- Chapter 15: subagents ---------------------------------------------------

def _text_thought(text):
    return Thought(text=text, raw_content=[{"type": "text", "text": text}])


class TaskEchoBrain(FakeBrain):
    """A child brain that answers with the task it was handed.

    The parent's `_spawn_subagent` builds children as `type(self.brain)(...)`, so
    a child brain only has to survive `(memory=..., tools=...)` and return a
    Thought. That is the seam these tests use instead of a model.
    """

    def think(self, conversation):
        task = str(conversation[-1].get("content"))
        return _text_thought(f"answered: {task}")


def _parent(**kwargs):
    return Agent(brain=FakeBrain(), tools=tools, mode="act", **kwargs)


def test_run_subagent_and_run_subagents_are_registered():
    names = [t.name for t in tools]
    assert "run_subagent" in names
    assert "run_subagents" in names
    assert RunSubagent().plan_safe is True   # children are read-only researchers
    assert RunSubagents().plan_safe is True


def test_run_subagent_returns_a_useful_error_without_a_spawn():
    """Embedding an Agent with a narrower context must not crash a tool."""
    result = RunSubagent().execute(ToolContext(), "look around")
    assert "subagents are not available" in result


def test_run_subagent_refuses_an_empty_task():
    result = RunSubagent().execute(ToolContext(spawn=lambda task: "never"), "   ")
    assert "empty" in result


def test_run_subagent_passes_the_task_to_spawn():
    seen = []

    def spawn(task):
        seen.append(task)
        return "the child's answer"

    result = RunSubagent().execute(ToolContext(spawn=spawn), "review app.py")
    assert result == "the child's answer"
    assert seen == ["review app.py"]


def test_run_subagent_survives_a_broken_child():
    def spawn(task):
        raise RuntimeError("child exploded")

    result = RunSubagent().execute(ToolContext(spawn=spawn), "review app.py")
    assert "subagent failed" in result and "child exploded" in result


def test_subagent_returns_only_its_answer_and_leaves_the_parent_conversation_alone():
    agent = _parent()
    agent.subagent_brain = lambda memory, tools: TaskEchoBrain(memory=memory, tools=tools)

    result = agent._spawn_subagent("check the tests")

    assert result == "answered: check the tests"
    assert agent.conversation == []          # nothing of the child's leaked in
    assert agent.subagents_spawned == 1


def test_subagent_tool_menu_drops_recursion_and_shared_state_writers():
    """The filter is the whole safety story: no recursion, no PLAN.md, no memory."""
    agent = _parent()
    names = [t.name for t in agent._subagent_tools()]
    for blocked in ("run_subagent", "run_subagents", "write_plan", "save_memory"):
        assert blocked not in names
    assert "read_file" in names and "search_codebase" in names


def test_subagent_runs_in_plan_mode_with_a_fresh_sandbox_and_bus(monkeypatch):
    """A child must not be able to disarm the parent's fence (ch14's trap)."""
    import nanocode

    real_agent = nanocode.Agent
    seen = {}

    class SpyAgent(real_agent):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            seen["child"] = self

    monkeypatch.setattr(nanocode, "Agent", SpyAgent)
    parent = real_agent(brain=FakeBrain(), tools=tools, mode="act")
    parent.subagent_brain = lambda memory, tools: TaskEchoBrain(memory=memory, tools=tools)

    parent._spawn_subagent("look around")
    child = seen["child"]

    assert child is not parent
    assert child.mode == "plan"                       # read-only by construction
    assert child.sandbox is not parent.sandbox        # arm() mutates, so never share
    assert child.sandbox.armed is False
    assert parent.sandbox.armed is True               # the parent is still armed
    assert child.hooks is not parent.hooks            # the parent hears 2 events, not N
    assert "write_file" not in [t["name"] for t in child.brain.tools]


def test_subagent_gets_its_own_iteration_budget():
    import nanocode

    agent = _parent()
    assert agent.max_iterations == nanocode.MAX_ITERATIONS
    assert agent.subagent_max_iterations == nanocode.SUBAGENT_MAX_ITERATIONS
    assert agent.subagent_max_iterations < agent.max_iterations


def test_parent_hears_only_subagent_start_and_end():
    agent = _parent()
    agent.subagent_brain = lambda memory, tools: TaskEchoBrain(memory=memory, tools=tools)
    heard = []
    agent.hooks.on("subagent_start", lambda **e: heard.append(("start", e["label"], e["task"])))
    agent.hooks.on("subagent_end", lambda **e: heard.append(("end", e["label"], e["ok"])))
    agent.hooks.on("tool_call", lambda **e: heard.append(("tool", e["name"])))

    agent._spawn_subagent("first")
    agent._spawn_subagent("second")

    assert heard == [
        ("start", "sub1", "first"),
        ("end", "sub1", True),
        ("start", "sub2", "second"),
        ("end", "sub2", True),
    ]


def test_subagent_events_are_known_hook_events():
    assert "subagent_start" in EVENTS
    assert "subagent_end" in EVENTS


def test_an_empty_task_does_not_spawn_anything():
    agent = _parent()
    result = agent._spawn_subagent("   ")
    assert "empty" in result
    assert agent.subagents_spawned == 0


def test_a_failing_brain_factory_is_reported_not_raised():
    def broken(memory, tools):
        raise ValueError("OPENROUTER_API_KEY not found")

    agent = _parent()
    agent.subagent_brain = broken
    result = agent._spawn_subagent("look around")
    assert "could not start a subagent" in result and "API_KEY" in result


def test_spawn_many_keeps_results_in_task_order():
    agent = _parent()
    agent.subagent_brain = lambda memory, tools: TaskEchoBrain(memory=memory, tools=tools)

    results = agent._spawn_many(["one", "two", "three"])

    assert results == ["answered: one", "answered: two", "answered: three"]


def test_spawn_many_really_runs_at_the_same_time():
    """A barrier only opens when all three children are inside think() at once.

    Sequential spawning deadlocks, times out, and the broken-barrier error shows
    up as three empty answers - which is exactly the failure this asserts against.
    """
    import threading

    barrier = threading.Barrier(3)

    class BarrierBrain(FakeBrain):
        def think(self, conversation):
            barrier.wait(timeout=5)
            return _text_thought("together")

    agent = _parent()
    agent.subagent_brain = lambda memory, tools: BarrierBrain(memory=memory, tools=tools)

    assert agent._spawn_many(["a", "b", "c"]) == ["together", "together", "together"]


def test_run_subagents_labels_each_answer():
    result = RunSubagents().execute(
        ToolContext(spawn_many=lambda tasks: [f"answer {t}" for t in tasks]),
        ["a", "b"],
    )
    assert "Subagent 1:\nanswer a" in result
    assert "Subagent 2:\nanswer b" in result


def test_run_subagents_falls_back_to_one_at_a_time():
    """No thread pool in the context? Sequential is the honest fallback."""
    result = RunSubagents().execute(
        ToolContext(spawn=lambda task: f"only {task}"),
        ["a", "b"],
    )
    assert "only a" in result and "only b" in result


def test_run_subagents_bounds_the_fan_out(monkeypatch):
    monkeypatch.setenv("NANOCODE_MAX_SUBAGENTS", "2")
    seen = []

    def spawn_many(tasks):
        seen.extend(tasks)
        return list(tasks)

    result = RunSubagents().execute(ToolContext(spawn_many=spawn_many), ["a", "b", "c", "d"])
    assert seen == ["a", "b"]
    assert "2 task(s) dropped" in result


def test_run_subagents_accepts_a_bare_string(monkeypatch):
    """Models sometimes send one string where the schema says array."""
    monkeypatch.delenv("NANOCODE_MAX_SUBAGENTS", raising=False)
    result = RunSubagents().execute(ToolContext(spawn_many=lambda tasks: list(tasks)), "solo")
    assert "Subagent 1:\nsolo" in result


def test_ui_scope_prefixes_only_the_current_thread():
    replies = {}

    def inside():
        with ui.scope("sub9"):
            replies["inside"] = ui.label()

    import threading

    _thread = threading.Thread(target=inside)
    _thread.start()
    _thread.join()

    assert replies["inside"] == "sub9"
    assert ui.label() == ""      # this thread never saw it


def test_each_subagent_gets_its_own_colour():
    """Colour is the fast cue in a fan-out, so no two children may share one."""
    colours = [ui.subagent_color(f"sub{index}") for index in range(1, len(ui.subagent_palette()) + 1)]
    assert len(set(colours)) == len(colours)
    assert ui.subagent_color("sub1") == colours[0]      # stable, not random
    assert ui.subagent_color("sub9") == colours[0]      # more children than colours: cycle
    assert ui.subagent_style("sub2").endswith("bold")   # palette colour + shared weight


def test_the_palette_is_data_in_ui_json():
    cfg = ui.load_config()
    assert cfg["subagents"]["palette"] == ui.subagent_palette()
    assert len(ui.subagent_palette()) >= 4


def test_palette_falls_back_when_ui_json_has_no_subagents_section(tmp_path):
    """A chapter with an older ui.json must still get colours, not a KeyError."""
    try:
        ui.configure(path=tmp_path / "missing.json")
        assert len(ui.subagent_palette()) == 8
        assert ui.subagent_style("sub2").endswith("bold")
    finally:
        ui.configure()  # restore the shipped ui.json


def test_hook_event_paints_the_child_label_in_its_own_colour():
    """subagent_start/end are the parent's lines, so the label carries the colour."""
    class Capture:
        def __init__(self):
            self.objects = []

        def print(self, *objects, **kwargs):
            self.objects.extend(objects)

        def input(self, *args, **kwargs):
            raise EOFError

    capture = Capture()
    ui.configure(console=capture)
    try:
        ui.hook_event("subagent_start", "review the tests", subagent_label="sub2")
    finally:
        ui.configure()  # back to the real console for every other test

    line = capture.objects[-1]
    spans = [line.plain[span.start:span.end] for span in line.spans]
    label_span = next(text for text in spans if "sub2" in text)
    style = next(span.style for span in line.spans
                 if "sub2" in line.plain[span.start:span.end])
    assert "sub2" in label_span
    assert ui.subagent_color("sub2") in style


# --- Chapter 15: the workflow patterns --------------------------------------

def test_fan_out_returns_answers_in_order():
    assert workflows.fan_out(lambda task: task.upper(), ["a", "b", "c"]) == ["A", "B", "C"]
    assert workflows.fan_out(lambda task: task, []) == []


def test_pipeline_feeds_each_stage_the_last_answer():
    seen = []

    def spawn(task):
        seen.append(task)
        return f"result{len(seen)}"

    out = workflows.pipeline(spawn, "the task", stages=["first", "second", "third"])

    assert out == "result3"
    assert "the task" in seen[0]
    assert "result1" in seen[1]          # stage 2 received stage 1's output
    assert "result2" in seen[2]
    assert "Stage 2 of 3" in seen[1]


def test_pipeline_with_no_stages_returns_the_task():
    assert workflows.pipeline(lambda task: "never", "as-is", stages=[]) == "as-is"


def test_map_reduce_shows_the_reducer_every_task_and_answer():
    prompts = []

    def spawn(task):
        prompts.append(task)
        return f"answer to {len(prompts)}"

    out = workflows.map_reduce(spawn, ["alpha", "beta"], "merge them")

    assert out == "answer to 3"                       # the reducer answered last
    assert "### Task 1\nalpha" in prompts[-1]
    assert "### Answer 2\nanswer to 2" in prompts[-1]


def test_critic_loop_writes_critiques_and_revises_each_round():
    prompts = []

    def spawn(task):
        prompts.append(task)
        return f"draft {len(prompts)}"

    out = workflows.critic_loop(spawn, "explain it", rounds=2)

    assert out == "draft 5"            # 1 draft + 2 x (critique + revise)
    assert "Critique the draft" in prompts[1]
    assert "Revise the draft" in prompts[2]
    assert "draft 3" in prompts[3]     # round two critiques round one's revision


def test_patterns_are_described_for_the_demo():
    text = workflows.describe()
    for name, _what, _when in workflows.PATTERNS:
        assert name in text
        assert "when:" in text
