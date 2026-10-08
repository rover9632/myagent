from __future__ import annotations

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.prompts import SYSTEM_PROMPT
from app.config import Settings
from app.sandbox import DockerSandbox
from app.tools.execution import build_execution_tools
from app.tools.web import build_web_tools


def build_agent(settings: Settings, sandbox: DockerSandbox):
    model = ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        use_responses_api=False,
        # One tool call at a time makes the MVP safer because all tools share one workspace.
        model_kwargs={"parallel_tool_calls": False},
    )

    tools = [
        *build_web_tools(
            api_key=settings.tavily_api_key,
            max_results=settings.tavily_max_results,
        ),
        *build_execution_tools(sandbox),
    ]

    checkpointer = InMemorySaver()

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
