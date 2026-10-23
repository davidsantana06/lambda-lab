from openai import APIError, APIStatusError
from typing import Any
import chainlit as cl

from database import create_tables
from services.agent_service import answer_question
from services.llm_service import TRANSIENT_STATUS_CODES
from services.tools_service import call_tool


@cl.on_app_startup
async def start_app():
    create_tables()


@cl.on_chat_start
async def start_chat():
    cl.user_session.set("history", [])


@cl.on_message
async def answer_message(message: cl.Message):
    history = cl.user_session.get("history")
    try:
        answer, cache_similarity = await answer_question(
            message.content,
            history,
            tool_caller=call_tool_in_step,
        )
    except APIError as error:
        is_transient = (
            isinstance(error, APIStatusError)
            and error.status_code in TRANSIENT_STATUS_CODES
        )
        content = (
            "O Gemini está sobrecarregado ou atingiu o limite de requisições. "
            "Tente de novo mais tarde."
            if is_transient
            else f"Não consegui falar com o modelo agora: {error.message}"
        )
        await cl.Message(content=content).send()
        return
    except Exception as error:
        await cl.Message(content=f"Algo deu errado ao responder: {error}").send()
        return

    if cache_similarity is not None:
        similarity = f"{cache_similarity:.2f}".replace(".", ",")
        answer = (
            f"*♻️ Resposta do cache semântico (similaridade {similarity}).*\n\n{answer}"
        )

    await cl.Message(content=answer).send()


async def call_tool_in_step(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with cl.Step(name=name, type="tool") as step:
        step.input = arguments
        result = await call_tool(name, arguments)
        step.output = result
        step.is_error = "error" in result

    return result
