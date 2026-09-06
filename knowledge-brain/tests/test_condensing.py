import uuid
from unittest.mock import AsyncMock, patch

from openai import OpenAIError

from app.core.circuit_breaker import CircuitOpenError
from app.models.conversation import RecentTurn
from app.repositories.conversation_repository import ConversationRepository
from app.services.condensing import condense_question, get_effective_question, update_recent_turns_cache


async def test_condense_question_falls_back_to_the_raw_question_when_the_response_has_no_choices():
    """A malformed/content-filtered OpenAI response with an empty choices list must degrade
    gracefully, not raise an uncaught IndexError from inside a request that looked handled.
    """
    fake_response = AsyncMock()
    fake_response.choices = []

    with patch(
        "app.services.condensing.circuit_breaker.call", new=AsyncMock(return_value=fake_response)
    ):
        result = await condense_question("What about part-time?", [RecentTurn(question="q", answer="a")])

    assert result == "What about part-time?"


async def test_a_brand_new_conversation_never_condenses(db_session):
    """None means nothing to condense against — the question passes through as-is."""
    with patch(
        "app.services.condensing.condense_question",
        new=AsyncMock(side_effect=AssertionError("should never be called")),
    ):
        question, recent_turns = await get_effective_question("How many vacation days?", None)

    assert question == "How many vacation days?"
    assert recent_turns == []


async def test_an_existing_conversation_with_no_turns_yet_does_not_condense(db_session):
    """A conversation that genuinely has no prior turns has nothing to condense against either."""
    repository = ConversationRepository(db_session)
    created = await repository.create_conversation("user-1", "New thread")
    conversation = await repository.get_conversation_for_user(created.id, "user-1")

    with (
        patch("app.services.condensing.get_recent_turns", new=AsyncMock(return_value=None)),
        patch(
            "app.services.condensing.condense_question",
            new=AsyncMock(side_effect=AssertionError("should never be called")),
        ),
    ):
        question, recent_turns = await get_effective_question("What about carryover?", conversation)

    assert question == "What about carryover?"
    assert recent_turns == []


async def test_uses_cached_recent_turns_when_available(db_session):
    repository = ConversationRepository(db_session)
    created = await repository.create_conversation("user-1", "Leave policy")
    conversation = await repository.get_conversation_for_user(created.id, "user-1")
    cached_turns = [{"question": "How many vacation days?", "answer": "20 days."}]

    with (
        patch("app.services.condensing.get_recent_turns", new=AsyncMock(return_value=cached_turns)),
        patch(
            "app.services.condensing.condense_question",
            new=AsyncMock(return_value="How many vacation days do part-time employees get?"),
        ) as mock_condense,
    ):
        question, recent_turns = await get_effective_question("What about part-time?", conversation)

    assert question == "How many vacation days do part-time employees get?"
    assert recent_turns == [RecentTurn(question="How many vacation days?", answer="20 days.")]
    mock_condense.assert_awaited_once_with("What about part-time?", recent_turns)


async def test_falls_back_to_the_conversations_own_loaded_turns_on_a_cache_miss(db_session):
    """A Redis miss (or outage) still finds the same recent turns — from the conversation object
    get_conversation_for_user already eager-loaded, not a second database query.
    """
    repository = ConversationRepository(db_session)
    created = await repository.create_conversation("user-1", "Leave policy")
    await repository.add_turn(
        created.id,
        raw_question="How many vacation days?",
        condensed_question="How many vacation days?",
        answer="20 days.",
        sources=[],
        confidence=0.9,
        domains_used=["HR"],
        correlation_id="corr-1",
    )
    conversation = await repository.get_conversation_for_user(created.id, "user-1")

    with (
        patch("app.services.condensing.get_recent_turns", new=AsyncMock(return_value=None)),
        patch(
            "app.services.condensing.condense_question",
            new=AsyncMock(return_value="condensed question"),
        ) as mock_condense,
    ):
        question, recent_turns = await get_effective_question("What about part-time?", conversation)

    assert question == "condensed question"
    assert recent_turns == [RecentTurn(question="How many vacation days?", answer="20 days.")]
    mock_condense.assert_awaited_once_with("What about part-time?", recent_turns)


async def test_falls_back_to_the_conversations_own_turns_when_the_cache_holds_an_unexpected_shape(
    db_session,
):
    """A cached value that isn't a valid {question, answer} shape must degrade gracefully, not crash."""
    repository = ConversationRepository(db_session)
    created = await repository.create_conversation("user-1", "Leave policy")
    await repository.add_turn(
        created.id,
        raw_question="How many vacation days?",
        condensed_question="How many vacation days?",
        answer="20 days.",
        sources=[],
        confidence=0.9,
        domains_used=["HR"],
        correlation_id="corr-1",
    )
    conversation = await repository.get_conversation_for_user(created.id, "user-1")

    with (
        patch(
            "app.services.condensing.get_recent_turns",
            new=AsyncMock(return_value=[{"unexpected": "shape"}]),
        ),
        patch(
            "app.services.condensing.condense_question",
            new=AsyncMock(return_value="condensed question"),
        ) as mock_condense,
    ):
        question, recent_turns = await get_effective_question("What about part-time?", conversation)

    assert question == "condensed question"
    assert recent_turns == [RecentTurn(question="How many vacation days?", answer="20 days.")]
    mock_condense.assert_awaited_once_with("What about part-time?", recent_turns)


async def test_falls_back_to_the_raw_question_when_condensing_circuit_is_open(db_session):
    repository = ConversationRepository(db_session)
    created = await repository.create_conversation("user-1", "Leave policy")
    conversation = await repository.get_conversation_for_user(created.id, "user-1")
    cached_turns = [{"question": "How many vacation days?", "answer": "20 days."}]

    with (
        patch("app.services.condensing.get_recent_turns", new=AsyncMock(return_value=cached_turns)),
        patch(
            "app.services.condensing.condense_question",
            new=AsyncMock(side_effect=CircuitOpenError("condensing is down")),
        ),
    ):
        question, recent_turns = await get_effective_question("What about part-time?", conversation)

    assert question == "What about part-time?"
    assert recent_turns == [RecentTurn(question="How many vacation days?", answer="20 days.")]


async def test_falls_back_to_the_raw_question_when_condensing_errors(db_session):
    repository = ConversationRepository(db_session)
    created = await repository.create_conversation("user-1", "Leave policy")
    conversation = await repository.get_conversation_for_user(created.id, "user-1")
    cached_turns = [{"question": "How many vacation days?", "answer": "20 days."}]

    with (
        patch("app.services.condensing.get_recent_turns", new=AsyncMock(return_value=cached_turns)),
        patch(
            "app.services.condensing.condense_question",
            new=AsyncMock(side_effect=OpenAIError("boom")),
        ),
    ):
        question, recent_turns = await get_effective_question("What about part-time?", conversation)

    assert question == "What about part-time?"
    assert recent_turns == [RecentTurn(question="How many vacation days?", answer="20 days.")]


async def test_update_recent_turns_cache_seeds_a_brand_new_conversations_first_turn():
    conversation_id = uuid.uuid4()

    with patch("app.services.condensing.cache_recent_turns", new=AsyncMock()) as mock_cache_write:
        await update_recent_turns_cache(conversation_id, [], "How many vacation days?", "20 days.")

    mock_cache_write.assert_awaited_once_with(
        str(conversation_id), [{"question": "How many vacation days?", "answer": "20 days."}]
    )


async def test_update_recent_turns_cache_appends_the_new_turn():
    conversation_id = uuid.uuid4()
    recent_turns = [RecentTurn(question="How many vacation days?", answer="20 days.")]

    with patch("app.services.condensing.cache_recent_turns", new=AsyncMock()) as mock_cache_write:
        await update_recent_turns_cache(
            conversation_id, recent_turns, "Can it be carried over?", "Yes, up to 5 days."
        )

    mock_cache_write.assert_awaited_once_with(
        str(conversation_id),
        [
            {"question": "How many vacation days?", "answer": "20 days."},
            {"question": "Can it be carried over?", "answer": "Yes, up to 5 days."},
        ],
    )


async def test_update_recent_turns_cache_trims_to_the_configured_window():
    """Once already at the window size, adding a turn should drop the oldest, not just grow forever."""
    conversation_id = uuid.uuid4()
    recent_turns = [
        RecentTurn(question="Q1", answer="A1"),
        RecentTurn(question="Q2", answer="A2"),
        RecentTurn(question="Q3", answer="A3"),
    ]

    with patch("app.services.condensing.cache_recent_turns", new=AsyncMock()) as mock_cache_write:
        await update_recent_turns_cache(conversation_id, recent_turns, "Q4", "A4")

    mock_cache_write.assert_awaited_once_with(
        str(conversation_id),
        [
            {"question": "Q2", "answer": "A2"},
            {"question": "Q3", "answer": "A3"},
            {"question": "Q4", "answer": "A4"},
        ],
    )
