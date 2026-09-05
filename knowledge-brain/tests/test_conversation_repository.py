import asyncio

from app.repositories.conversation_repository import ConversationRepository


async def test_create_conversation_stores_title_and_owner(db_session):
    repository = ConversationRepository(db_session)

    conversation = await repository.create_conversation("user-1", "What's our vacation policy?")

    assert conversation.user_id == "user-1"
    assert conversation.title == "What's our vacation policy?"


async def test_add_turn_stores_every_field(db_session):
    repository = ConversationRepository(db_session)
    conversation = await repository.create_conversation("user-1", "Leave policy")

    turn = await repository.add_turn(
        conversation.id,
        raw_question="How many vacation days do I get?",
        condensed_question="How many vacation days do I get?",
        answer="20 days per year.",
        sources=[{"document_id": "doc-1", "filename": "hr.txt", "chunk_text": "20 days"}],
        confidence=0.87,
        domains_used=["HR"],
        correlation_id="corr-1",
    )

    assert turn.conversation_id == conversation.id
    assert turn.raw_question == "How many vacation days do I get?"
    assert turn.answer == "20 days per year."
    assert turn.sources == [{"document_id": "doc-1", "filename": "hr.txt", "chunk_text": "20 days"}]
    assert turn.confidence == 0.87
    assert turn.domains_used == ["HR"]
    assert turn.correlation_id == "corr-1"


async def test_add_turn_bumps_the_conversations_updated_at(db_session):
    repository = ConversationRepository(db_session)
    conversation = await repository.create_conversation("user-1", "Leave policy")
    original_updated_at = conversation.updated_at

    await asyncio.sleep(0.01)
    await repository.add_turn(
        conversation.id,
        raw_question="q",
        condensed_question="q",
        answer="a",
        sources=[],
        confidence=None,
        domains_used=[],
        correlation_id="corr-1",
    )

    refreshed = await repository.get_conversation_for_user(conversation.id, "user-1")
    assert refreshed.updated_at > original_updated_at


async def test_list_conversations_for_user_orders_most_recently_active_first(db_session):
    repository = ConversationRepository(db_session)
    first = await repository.create_conversation("user-1", "First conversation")
    await asyncio.sleep(0.01)
    second = await repository.create_conversation("user-1", "Second conversation")

    # Adding a turn to the older conversation should float it back to the top.
    await asyncio.sleep(0.01)
    await repository.add_turn(
        first.id,
        raw_question="q",
        condensed_question="q",
        answer="a",
        sources=[],
        confidence=None,
        domains_used=[],
        correlation_id="corr-1",
    )

    conversations = await repository.list_conversations_for_user("user-1")

    assert [c.id for c in conversations] == [first.id, second.id]


async def test_list_conversations_for_user_excludes_other_users(db_session):
    repository = ConversationRepository(db_session)
    await repository.create_conversation("user-1", "Mine")
    await repository.create_conversation("user-2", "Not mine")

    conversations = await repository.list_conversations_for_user("user-1")

    assert [c.title for c in conversations] == ["Mine"]


async def test_get_conversation_for_user_returns_none_for_a_stranger(db_session):
    repository = ConversationRepository(db_session)
    conversation = await repository.create_conversation("user-1", "Private thread")

    result = await repository.get_conversation_for_user(conversation.id, "user-2")

    assert result is None


async def test_get_conversation_for_user_includes_turns_in_order(db_session):
    repository = ConversationRepository(db_session)
    conversation = await repository.create_conversation("user-1", "Leave policy")
    await repository.add_turn(
        conversation.id,
        raw_question="first question",
        condensed_question="first question",
        answer="a1",
        sources=[],
        confidence=None,
        domains_used=[],
        correlation_id="corr-1",
    )
    await repository.add_turn(
        conversation.id,
        raw_question="second question",
        condensed_question="second question",
        answer="a2",
        sources=[],
        confidence=None,
        domains_used=[],
        correlation_id="corr-2",
    )

    result = await repository.get_conversation_for_user(conversation.id, "user-1")

    assert [t.raw_question for t in result.turns] == ["first question", "second question"]
