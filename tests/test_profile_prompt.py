from __future__ import annotations

from datetime import UTC, datetime

from conftest import FakeAgent, FakeUserStore

from app.agent.factory import profiled_system_prompt
from app.agent.prompts import (
    ATTR_MAX_KEYS,
    BIO_LIMIT,
    NOTE_LIMIT,
    SYSTEM_PROMPT,
    compose_system_prompt,
    format_user_profile,
)
from app.agent.service import AgentService
from app.context import get_user_profile
from app.user_store import ProfileSnapshot

NOW = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)


def snapshot(**overrides) -> ProfileSnapshot:
    base = dict(
        username="alice",
        display_name="Alice Wang",
        bio="backend engineer",
        locale="zh-CN",
        timezone="Asia/Shanghai",
        attributes={"city": "Hangzhou", "team": "platform"},
        email="alice@example.com",
        phone="+8613800000000",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return ProfileSnapshot(**base)


# --- format_user_profile -------------------------------------------------


def test_format_renders_all_fields():
    note = format_user_profile(snapshot(), now=NOW)
    assert note.startswith("# Current user profile")
    assert "- username: alice" in note
    assert "- display_name: Alice Wang" in note
    assert "- locale: zh-CN" in note
    assert "- current_time: 2026-11-10 14:30 Tuesday (Asia/Shanghai)" in note
    assert "- email: alice@example.com" in note
    assert "- phone: +8613800000000" in note
    assert "- bio: backend engineer" in note
    assert "- attributes: city=Hangzhou, team=platform" in note
    assert "- member_since: 2026-05-01" in note


def test_format_omits_absent_optional_fields():
    note = format_user_profile(
        snapshot(
            display_name=None,
            bio=None,
            email=None,
            phone=None,
            attributes={},
            created_at=None,
        ),
        now=NOW,
    )
    for gone in ("display_name", "email", "phone", "bio", "attributes", "member_since"):
        assert f"- {gone}:" not in note
    assert "- username: alice" in note


def test_format_truncates_bio_and_collapses_newlines():
    note = format_user_profile(snapshot(bio="line1\n\tline2 " + "x" * 600), now=NOW)
    bio_line = next(line for line in note.splitlines() if line.startswith("- bio:"))
    assert "\t" not in note.split("- bio:")[1].split("- attributes")[0]
    assert len(bio_line) <= len("- bio: ") + BIO_LIMIT + 1
    assert bio_line.endswith("…")


def test_format_caps_attribute_keys_and_json_dumps_values():
    attrs = {f"k{i}": {"nested": i} for i in range(ATTR_MAX_KEYS + 5)}
    note = format_user_profile(snapshot(attributes=attrs), now=NOW)
    attr_line = next(line for line in note.splitlines() if line.startswith("- attributes:"))
    rendered = attr_line.split("- attributes: ")[1].split(", ")
    # Only the first ATTR_MAX_KEYS (sorted) survive, dict values are JSON-encoded.
    assert len(rendered) == ATTR_MAX_KEYS
    assert 'k0={"nested": 0}' in rendered


def test_format_survives_invalid_timezone():
    note = format_user_profile(snapshot(timezone="Not/AZone"), now=NOW)
    assert "profile timezone invalid" in note
    assert "06:30" in note  # UTC fallback


def test_format_caps_total_length():
    huge = "y" * 400
    snap = snapshot(bio=huge, attributes={f"k{i}": huge for i in range(10)})
    note = format_user_profile(snap, now=NOW)
    assert len(note) <= NOTE_LIMIT + 1


# --- compose_system_prompt / middleware wiring ---------------------------


def test_compose_without_profile_is_plain_system_prompt():
    assert compose_system_prompt(None) == SYSTEM_PROMPT
    assert compose_system_prompt("") == SYSTEM_PROMPT


def test_compose_appends_profile_block():
    note = format_user_profile(snapshot(), now=NOW)
    composed = compose_system_prompt(note)
    assert composed.startswith(SYSTEM_PROMPT)
    assert composed.endswith(note)


def test_profiled_prompt_is_middleware():
    from langchain.agents.middleware.types import AgentMiddleware

    assert isinstance(profiled_system_prompt, AgentMiddleware)


# --- AgentService fetch/binding ------------------------------------------


class RecordingAgent(FakeAgent):
    """FakeAgent that snapshots the profile contextvar at model-call time."""

    def __init__(self, events):
        super().__init__(events)
        self.profiles_at_call: list[str | None] = []

    async def astream_events(self, payload, *, config=None, version=None):
        self.profiles_at_call.append(get_user_profile())
        async for event in super().astream_events(payload, config=config, version=version):
            yield event


async def test_stream_binds_profile_and_resets(fake_events):
    store = FakeUserStore()
    user = await store.create_user("alice", "pw12345678")
    await store.update_me(
        user.id, {"display_name": "Alice W", "bio": "music fan", "timezone": "Asia/Shanghai"}
    )
    agent = RecordingAgent(fake_events)
    service = AgentService(agent, store)

    out = [event async for event in service.stream(username="alice", thread_id="t", message="hi")]

    assert out[-1].type == "done"
    note = agent.profiles_at_call[0]
    assert note is not None and note.startswith("# Current user profile")
    assert "- display_name: Alice W" in note
    assert "- bio: music fan" in note
    assert "- timezone: Asia/Shanghai" in note

    # Case-insensitive lookup mirrors the real store; drain fully so the
    # service's finally-block reset runs.
    agent2 = RecordingAgent(fake_events)
    out2 = [
        event
        async for event in AgentService(agent2, store).stream(
            username="ALICE", thread_id="t", message="hi"
        )
    ]
    assert out2[-1].type == "done"
    assert agent2.profiles_at_call[0] is not None


async def test_stream_without_store_has_no_profile(fake_events):
    agent = RecordingAgent(fake_events)
    service = AgentService(agent)  # user_store=None: legacy constructor still valid
    out = [event async for event in service.stream(username="alice", thread_id="t", message="hi")]
    assert out[-1].type == "done"
    assert agent.profiles_at_call == [None]


async def test_stream_survives_profile_fetch_failure(fake_events):
    class BoomStore(FakeUserStore):
        async def profile_snapshot(self, username):
            raise RuntimeError("db hiccup")

    agent = RecordingAgent(fake_events)
    service = AgentService(agent, BoomStore())
    out = [event async for event in service.stream(username="alice", thread_id="t", message="hi")]
    assert [event.type for event in out][-1] == "done"
    assert "error" not in [event.type for event in out]
    assert agent.profiles_at_call == [None]


async def test_stream_unknown_user_gets_no_profile(fake_events):
    agent = RecordingAgent(fake_events)
    service = AgentService(agent, FakeUserStore())
    out = [event async for event in service.stream(username="ghost", thread_id="t", message="hi")]
    assert out[-1].type == "done"
    assert agent.profiles_at_call == [None]
