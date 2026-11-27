from typing import TypedDict

from mcp.server.fastmcp import FastMCP

from policy_bot.policy_catalog import Policy, matching_policies


class SearchResult(TypedDict):
    matches: list[Policy]


mcp = FastMCP("Sample academic policies")


@mcp.tool()
def search_academic_policy(query: str) -> SearchResult:
    """Search sample policies. Include the specific course and policy topic in the query."""
    return {"matches": matching_policies(query)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
