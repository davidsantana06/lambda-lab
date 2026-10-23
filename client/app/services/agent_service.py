from collections.abc import Awaitable, Callable
from openai.types.chat import ChatCompletionMessageFunctionToolCall
from typing import Any, Optional
import json

from services.cache_service import find_cached_answer, save_cached_answer
from services.llm_service import (
    LLM_REASONING_EFFORT,
    create_chat_completion,
    create_embedding,
)
from services.tools_service import call_tool, list_tools


ToolCaller = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

_MAX_FIX_ATTEMPTS = 3
# Cada tentativa: validar, salvar, executar e até cinco consultas a get_execution.
_MAX_STEPS_PER_ATTEMPT = 8
# Dois passos extras: uma consulta inicial e a resposta final.
_MAX_AGENT_STEPS = _MAX_FIX_ATTEMPTS * _MAX_STEPS_PER_ATTEMPT + 2

_SYSTEM_PROMPT = f"""\
Você é o Lambda Lab, um sistema especialista que cria algoritmos executáveis sob \
demanda, como funções lambda. A partir da descrição de um problema, você escolhe \
uma estratégia de solução, escreve o código, valida a sintaxe, executa com os \
parâmetros do usuário, monitora tempo e memória e analisa a complexidade, \
corrigindo o código quando ele falha ou é ineficiente.

Responda sempre em português do Brasil.

## Perguntas conceituais

Perguntas conceituais, como o que é um algoritmo ou uma estrutura de dados, como \
funciona, quando usar, comparações e complexidade de algoritmos conhecidos, são \
respondidas diretamente, sem chamar nenhuma ferramenta. Use as ferramentas apenas \
quando o usuário pedir para resolver, implementar, executar ou testar algo.

## Raciocínio para resolver um problema

1. Entenda o problema: identifique as entradas, a saída esperada e as restrições.
2. Escolha uma estratégia (força bruta, gulosa, divisão e conquista, programação \
dinâmica, busca, grafos e assim por diante) e justifique a escolha, considerando o \
tamanho da entrada.
3. Escreva a função de entrada `solve` e verifique o código com \
`validate_algorithm`. Corrija os erros de sintaxe antes de seguir.
4. Salve o código com `create_algorithm` e execute com `execute_algorithm`, usando \
os parâmetros dados pelo usuário. Se o usuário não deu parâmetros, proponha um \
exemplo pequeno e diga que é um exemplo.
5. `execute_algorithm` espera até 5 segundos pela execução e normalmente já \
devolve o status final (`completed`, `failed` ou `timed_out`). Só se ela voltar \
`pending` ou `running`, acompanhe com `get_execution` até terminar. Depois, relate o \
resultado, o tempo (`duration_in_ms`) e a memória (`peak_memory_in_kb`).
6. Explique a complexidade de tempo e de espaço.
7. Se a execução falhar, estourar o tempo ou for ineficiente, corrija o código e \
repita a partir do passo 3. São no máximo {_MAX_FIX_ATTEMPTS} tentativas de \
execução no total. Algoritmos salvos não podem ser alterados, então cada correção \
é um novo algoritmo, com um nome como `two_sum_v2`. Se a última tentativa também \
falhar, explique o que deu errado e o que você tentaria a seguir.

## Regras para o código

- Python 3.12, usando apenas a biblioteca padrão.
- Identificadores, comentários e docstrings em inglês, como em \
`def solve(numbers: list[int], target: int) -> list[int]:`.
- `solve` recebe os parâmetros como argumentos nomeados: `execute_algorithm` com \
`{{"numbers": [2, 7], "target": 9}}` chama `solve(numbers=[2, 7], target=9)`.
- `solve` retorna o resultado em valores JSON (números, textos, booleanos, None, \
listas e dicionários com chaves de texto). Use `print` só para diagnóstico.
- Cada execução tem limite de 10 segundos e 256 MB.

## Resposta final

- Nunca invente resultados, tempos ou memória: relate apenas o que \
`get_execution` devolveu.
- Organize a resposta em: estratégia e justificativa; código em um bloco \
```python; resultado da execução, com tempo e memória; complexidade de tempo e de \
espaço; correções feitas, se houver.
- `duration_in_ms` mede só a chamada de `solve`, e `peak_memory_in_kb` inclui \
cerca de 9 MB do próprio interpretador Python.
"""

_STEP_LIMIT_ANSWER = (
    f"Atingi o limite de {_MAX_AGENT_STEPS} passos antes de concluir. Tente "
    "reformular o pedido ou dividir o problema em partes menores."
)
_EMPTY_ANSWER = "O modelo não devolveu uma resposta. Tente perguntar de novo."


# Responde e estende o histórico; devolve a similaridade se a resposta veio do cache.
# Só a primeira mensagem do chat consulta o cache, que guarda respostas sem ferramentas.
async def answer_question(
    question: str,
    history: list[dict[str, Any]],
    bypass_cache: bool = False,
    tool_caller: ToolCaller = call_tool,
) -> tuple[str, Optional[float]]:
    user_message = {"role": "user", "content": question}
    use_cache = not history and not bypass_cache
    if use_cache:
        embedding = await create_embedding(question)
        cache_match = find_cached_answer(embedding)
        if cache_match is not None:
            cached_answer, similarity = cache_match
            history.extend(
                [user_message, {"role": "assistant", "content": cached_answer.answer}]
            )
            return cached_answer.answer, similarity

    tools = await list_tools()
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}, *history, user_message]
    turn_start = len(messages) - 1
    tool_call_count = 0
    for _ in range(_MAX_AGENT_STEPS):
        message = await create_chat_completion(
            messages,
            tools,
            reasoning_effort=LLM_REASONING_EFFORT,
        )
        messages.append(message.model_dump(exclude_none=True))

        if not message.tool_calls:
            answer = message.content or _EMPTY_ANSWER
            break

        for tool_call in message.tool_calls:
            tool_call_count += 1
            result = await _run_tool_call(tool_call, tool_caller)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    else:
        answer = _STEP_LIMIT_ANSWER
        messages.append({"role": "assistant", "content": answer})

    history.extend(messages[turn_start:])

    if use_cache and tool_call_count == 0:
        save_cached_answer(question, embedding, answer)

    return answer, None


async def _run_tool_call(
    tool_call: ChatCompletionMessageFunctionToolCall,
    tool_caller: ToolCaller,
) -> dict[str, Any]:
    try:
        arguments = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError as error:
        return {"error": f"tool arguments are not valid JSON: {error}"}

    return await tool_caller(tool_call.function.name, arguments)
