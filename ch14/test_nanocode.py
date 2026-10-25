"""Tests for Nanocode v1.0 (Chapter 14 - a sandbox for ACT mode).

Chapter 14 is chapter 13 plus sandbox.py: whenever ACT mode lets the agent write,
a policy decides *where*. Everything below the sandbox tests is the book's
original chapter-13 suite, unchanged.
"""

import os
import tempfile

import sandbox
import sounds
import ui
from hooks import EVENTS, Hooks
from nanocode import (
    Agent, AgentStop, Thought, ToolCall, Memory, ToolContext,
    ReadFile, WriteFile, WritePlan, ListFiles, SearchCodebase, SaveMemory, RunCommand, SearchWeb,
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
