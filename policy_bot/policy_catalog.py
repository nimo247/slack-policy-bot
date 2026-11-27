import json
import re
from pathlib import Path
from typing import TypedDict


class Policy(TypedDict):
    id: str
    title: str
    excerpt: str


POLICIES = json.loads(
    Path(__file__).with_name("policies.json").read_text(encoding="utf-8")
)


def matching_policies(query: str) -> list[Policy]:
    normalized = " " + " ".join(re.findall(r"[^\W_]+", query.casefold())) + " "
    return [
        {"id": row["id"], "title": row["title"], "excerpt": row["excerpt"]}
        for row in POLICIES
        if all(
            any(f" {phrase} " in normalized for phrase in alternatives)
            for alternatives in row["required_groups"]
        )
    ]
