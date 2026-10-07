from __future__ import annotations

import json

from langchain.tools import tool
from langchain_tavily import TavilySearch


def build_web_tools(*, api_key: str, max_results: int):
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required to enable web_search")

    tavily = TavilySearch(
        max_results=max_results,
        topic="general",
        search_depth="basic",
        include_raw_content=False,
        tavily_api_key=api_key,
    )

    @tool("web_search")
    async def web_search(query: str) -> str:
        """Search the public web for current or external information.

        Use this when the answer depends on recent information, online sources,
        documentation, news, product facts, or other web content.
        """
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")

        result = await tavily.ainvoke({"query": query})
        if not isinstance(result, dict):
            return json.dumps({"query": query, "result": result}, ensure_ascii=False)

        compact_results = []
        for item in result.get("results", []):
            if not isinstance(item, dict):
                continue
            compact_results.append(
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "content": item.get("content"),
                    "score": item.get("score"),
                }
            )

        payload = {
            "query": query,
            "answer": result.get("answer"),
            "results": compact_results,
        }
        return json.dumps(payload, ensure_ascii=False)

    return [web_search]
