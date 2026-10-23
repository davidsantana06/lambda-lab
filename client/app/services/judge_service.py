from typing import Any
import json
import os

from services.llm_service import create_chat_completion


JUDGE_MODEL = os.environ["JUDGE_MODEL"]
CRITERIA = ("correctness", "efficiency", "clarity")

_JUDGE_PROMPT = """\
Você é um avaliador rigoroso de um sistema especialista que resolve problemas de \
algoritmos: ele escolhe uma estratégia, escreve o código, executa com os parâmetros \
dados e explica a complexidade. Você recebe o problema, os parâmetros de entrada, a \
saída esperada, a complexidade de referência e a resposta do sistema, e dá notas \
inteiras de 1 a 5 em três critérios.

## Corretude (correctness)

- 5: o resultado relatado é igual à saída esperada e o código está correto.
- 3: o resultado está parcialmente certo, ou está certo mas o código tem falhas \
evidentes.
- 1: o resultado está errado, ausente ou não veio de uma execução.

## Eficiência (efficiency)

- 5: as complexidades de tempo e de espaço do código são iguais ou melhores que as \
de referência.
- 3: o código é pior que a referência, mas aceitável para a entrada dada.
- 1: o código é muito pior que a referência ou estourou o tempo.

## Clareza (clarity)

- 5: explica a estratégia e por que ela foi escolhida, mostra o código, relata \
resultado, tempo e memória da execução e analisa a complexidade, de forma \
organizada e em português do Brasil.
- 3: falta uma dessas partes ou a explicação é confusa.
- 1: a resposta é desorganizada ou difícil de entender.

Use 2 e 4 para casos intermediários. Avalie a complexidade pelo código mostrado, \
não pela complexidade que a resposta afirma ter. Considere equivalentes formatos que \
representam o mesmo valor, como true e True.

Responda apenas com um objeto JSON neste formato:
{"correctness": <1 a 5>, "efficiency": <1 a 5>, "clarity": <1 a 5>, \
"justification": "<até três frases em português do Brasil>"}
"""


def compose_question(case: dict[str, Any]) -> str:
    parameters = json.dumps(case["parameters"], ensure_ascii=False)
    return f"{case['problem']}\n\nExecute com estes parâmetros: {parameters}"


async def judge_answer(case: dict[str, Any], answer: str) -> dict[str, Any]:
    message = await create_chat_completion(
        [
            {"role": "system", "content": _JUDGE_PROMPT},
            {"role": "user", "content": _compose_evaluation(case, answer)},
        ],
        model=JUDGE_MODEL,
        response_format={"type": "json_object"},
    )
    return _parse_verdict(message.content or "")


def _compose_evaluation(case: dict[str, Any], answer: str) -> str:
    complexity = case["reference_complexity"]
    return (
        f"## Problema\n\n{case['problem']}\n\n"
        f"## Parâmetros de entrada\n\n"
        f"{json.dumps(case['parameters'], ensure_ascii=False)}\n\n"
        f"## Saída esperada\n\n"
        f"{json.dumps(case['expected_output'], ensure_ascii=False)}\n\n"
        f"## Complexidade de referência\n\n"
        f"Tempo: {complexity['time']}. Espaço: {complexity['space']}.\n\n"
        f"## Resposta do sistema\n\n{answer}"
    )


def _parse_verdict(content: str) -> dict[str, Any]:
    verdict = json.loads(content)
    scores = {criterion: verdict.get(criterion) for criterion in CRITERIA}
    if not all(
        isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 5
        for score in scores.values()
    ):
        raise ValueError(f"judge returned invalid scores: {content}")

    return {**scores, "justification": str(verdict.get("justification", "")).strip()}
