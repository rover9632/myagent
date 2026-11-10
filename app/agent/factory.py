from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.prompts import SYSTEM_PROMPT, compose_system_prompt
from app.config import Settings
from app.context import get_user_profile
from app.sandbox import DockerSandbox
from app.tools.execution import build_execution_tools
from app.tools.genpass import build_genpass_tools
from app.tools.imgs2pdf import build_imgs2pdf_tools
from app.tools.pdf2imgs import build_pdf2imgs_tools
from app.tools.web import build_web_tools


@dynamic_prompt
def profiled_system_prompt(request: ModelRequest) -> str:
    """Per-model-call system prompt: base + the profile block AgentService
    bound to this request's context (same contextvars pattern as the tools).
    Unbound/no profile falls back to plain SYSTEM_PROMPT, so nothing about
    history or the static prompt changes."""
    return compose_system_prompt(get_user_profile())


def build_agent(
    settings: Settings,
    sandbox: DockerSandbox,
    checkpointer: BaseCheckpointSaver,
):
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
        # Host-side file tools: they run in the FastAPI process directly on
        # the session workspace and return cloud URLs for generated files.
        *build_genpass_tools(),
        *build_imgs2pdf_tools(sandbox),
        *build_pdf2imgs_tools(sandbox),
    ]

    return create_agent(
        model=model,
        tools=tools,
        # Static base for anything that inspects the graph without the
        # middleware; every real model call gets the composed prompt below.
        system_prompt=SYSTEM_PROMPT,
        middleware=[profiled_system_prompt],
        checkpointer=checkpointer,
    )
