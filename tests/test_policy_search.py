import pytest

from policy_bot.policy_mcp import search_academic_policy


@pytest.mark.parametrize(
    "query",
    [
        "Machine Learning prerequisite",
        "chemistry lab timings",
        "chemistry lab prerequisite",
        "when is the final exam",
        "when does registration open for Embedded Systems Lab",
        "which electives are offered",
    ],
)
def test_search_rejects_queries_without_the_policy_topic_and_intent(query):
    assert search_academic_policy(query) == {"matches": []}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("What prerequisite do I need for Embedded Systems Lab?", "LAB-101"),
        ("How do I withdraw from an elective?", "COURSE-202"),
        ("How do I request a make-up exam?", "EXAM-303"),
        ("What if I missed the final exam?", "EXAM-303"),
    ],
)
def test_search_returns_policy_when_the_topic_and_intent_match(query, expected):
    assert [policy["id"] for policy in search_academic_policy(query)["matches"]] == [
        expected
    ]
