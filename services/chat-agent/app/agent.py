"""Module 4 core: the tool-calling loop.

Pipeline (proposal 4(d)): user question -> LLM agent -> tool call (SQL on the transaction
database, the Module 3 forecast API, or Module 5's annual reports) -> result -> plain-English answer.

The loop is written out by hand so that every tool call is recorded in `steps`: the UI shows
them, which is what makes the answers checkable. It works with any provider in
spendcheck_common.llm (OpenRouter free models or Claude).
"""

import logging
from datetime import date

from psycopg_pool import ConnectionPool
from spendcheck_common.llm import LLM

from .config import Settings
from .prompts import SYSTEM_PROMPT, date_context, persona_instructions
from .schemas import ChatRequest, ChatResponse, ReportCitation, ToolStep
from .tools import TOOL_DEFINITIONS, ToolContext, ToolResult, execute_tool

log = logging.getLogger(__name__)

REFUSAL_ANSWER = "Sorry, I can't help with that. I can answer questions about your spending or about SGX-listed companies."
STEP_LIMIT_ANSWER = "I couldn't finish working that out. Could you ask a narrower question?"


def run_agent(
    request: ChatRequest,
    user_id: str,
    request_id: str | None,
    *,
    llm: LLM,
    pool: ConnectionPool,
    settings: Settings,
    today: date,
) -> ChatResponse:
    """Answer one question, letting the LLM call tools until it has what it needs."""
    messages: list[dict] = [{"role": turn.role, "content": turn.content} for turn in request.history]
    messages.append({
        "role": "user",
        "content": f"{date_context(today, settings.timezone)}\n\n{request.message}",
    })
    ctx = ToolContext(user_id=user_id, request_id=request_id, pool=pool, settings=settings, today=today)
    steps: list[ToolStep] = []
    citations: list[ReportCitation] = []

    def respond(answer: str) -> ChatResponse:
        return ChatResponse(answer=answer, mode="agent", steps=steps, citations=citations, model=llm.model)

    system = SYSTEM_PROMPT + persona_instructions(request.persona)
    for _ in range(settings.agent_max_steps):
        reply = llm.chat(
            system=system,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            max_tokens=settings.llm_max_tokens,
            effort=settings.llm_effort,
        )
        if reply.stop == "refusal":
            return respond(REFUSAL_ANSWER)
        if reply.stop != "tool_use":
            # finished (or ran out of tokens): the text so far is the answer
            return respond(reply.text.strip() or STEP_LIMIT_ANSWER)

        messages.append(reply.assistant_message)
        results = []
        for call in reply.tool_calls:
            if call.input is None:   # the model produced broken arguments: tell it, so it can retry
                result = ToolResult(f"Invalid tool arguments: {call.parse_error}", is_error=True)
            else:
                result = execute_tool(call.name, call.input, ctx)
            content = result.content[: settings.tool_output_chars]
            steps.append(ToolStep(tool=call.name, input=call.input or {},
                                  output_preview=content[:500], is_error=result.is_error))
            citations.extend(ReportCitation.model_validate(c) for c in result.citations)
            results.append((call.id, content, result.is_error))
        messages.extend(llm.tool_results(results))

    log.warning("agent hit the step limit (%d) for request %s", settings.agent_max_steps, request_id)
    return respond(STEP_LIMIT_ANSWER)
