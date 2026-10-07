from __future__ import annotations

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from app.config import Settings
from app.sandbox import DockerSandbox
from app.tools.execution import build_execution_tools
from app.tools.web import build_web_tools


SYSTEM_PROMPT = """
You are a general-purpose AI agent.

Available tools:
- web_search: search the public web for current or external information.
- bash_exec: execute shell commands in an isolated Docker sandbox.
- python_exec: execute Python code in the isolated Docker sandbox.
- python_run_script: run an existing Python script in the sandbox workspace.

Tool selection rules:
1. Answer directly when no tool is needed.
2. Use web_search for current, recent, or externally sourced information.
3. Use python_exec for calculations and data processing instead of doing large calculations mentally.
4. Use bash_exec for shell operations and workspace/file operations.
5. Use python_run_script when the user explicitly refers to an existing script in the workspace.
6. A sandbox command is successful only when its tool result has exit_code == 0.
7. Do not claim that a file was created, a command succeeded, or a script completed unless the tool result confirms it.
8. Keep tool calls focused and avoid unnecessary repeated calls.
9. Never expose internal tool arguments or hidden reasoning; provide a concise summary of actions and results.
10. When web_search returns URLs, cite them as Markdown links when they are relevant to the final answer.
""".strip()


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
