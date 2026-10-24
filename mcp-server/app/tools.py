from typing import Any, Optional
import time

from client import compose_search_params, request
from models import Algorithm, AlgorithmValidation, Execution, ExecutionStatus


_EXECUTION_WAIT_IN_SECONDS = 5
_EXECUTION_POLL_INTERVAL_IN_SECONDS = 0.2
_UNFINISHED_STATUSES = ("pending", "running")


def check_algorithm_service_health() -> dict[str, str]:
    """Verifica se o serviço de algoritmos está acessível e respondendo.

    Use para distinguir uma indisponibilidade do serviço de uma busca que
    simplesmente não encontrou nada, ou quando outras ferramentas falham
    repetidamente ao acessar o serviço.

    Returns:
        O status informado, como {"status": "ok", "service": "algorithm"}.
    """
    return request("GET", "/health")


def validate_algorithm(
    source_code: str,
    entry_point: str = "solve",
) -> AlgorithmValidation:
    """Verifica o código-fonte de um algoritmo sem salvá-lo nem executá-lo.

    Analisa o código Python e confere se o ponto de entrada é uma função comum
    definida no nível do módulo, e não aninhada, assíncrona ou lambda. Use
    antes de create_algorithm para detectar erros de sintaxe cedo. O código
    não é executado, então erros em tempo de execução só aparecem ao
    executá-lo.

    O resultado tem valid igual a true quando o código está pronto para ser
    salvo. Caso contrário, valid é false e message explica o problema, com a
    linha e a coluna (contadas a partir de 1) de um erro de sintaxe. Os campos
    line e column ficam vazios quando o problema é a falta do ponto de entrada.

    Args:
        source_code: Módulo Python 3.12 completo que define o ponto de entrada.
        entry_point: Nome da função que as execuções vão chamar.

    Returns:
        O resultado da validação, com valid, line, column e message.
    """
    payload = {"source_code": source_code, "entry_point": entry_point}
    return AlgorithmValidation.model_validate(
        request("POST", "/algorithms/validate", json=payload)
    )


def create_algorithm(
    name: str,
    description: str,
    source_code: str,
    entry_point: str = "solve",
) -> Algorithm:
    """Salva um novo algoritmo para que ele possa ser executado.

    O código-fonte é validado antes, exatamente como em validate_algorithm, e
    nada é salvo quando ele é inválido: a ferramenta falha com a linha, a
    coluna e a mensagem do erro. Algoritmos salvos nunca podem ser editados
    nem apagados, então corrigir um significa criar um novo algoritmo, como
    "two_sum_v2". Em caso de sucesso, devolve o algoritmo salvo com o id de
    que execute_algorithm precisa.

    O código deve seguir o contrato de execução:
    - as execuções chamam o ponto de entrada só com argumentos nomeados, como
      em solve(**arguments), então os nomes dos parâmetros devem ser iguais a
      essas chaves;
    - o ponto de entrada devolve o resultado, e os prints ficam separados, no
      stdout da execução, então use print só para diagnóstico;
    - devolva valores JSON (números, textos, booleanos, None, listas e
      dicionários com chaves de texto); qualquer outro valor, como um set,
      volta como o seu repr;
    - use apenas a biblioteca padrão do Python;
    - o código no nível do módulo roda uma vez antes da chamada e fica fora da
      medição de tempo, e blocos protegidos por if __name__ == "__main__"
      nunca rodam;
    - cada execução tem limite de 10 segundos e de 256 MB de memória.

    Args:
        name: Identificador curto do algoritmo, como "fibonacci_dp".
        description: Problema que o algoritmo resolve e a estratégia que ele
            usa, como "Números de Fibonacci por programação dinâmica bottom-up".
        source_code: Módulo Python 3.12 completo que define o ponto de entrada.
        entry_point: Nome da função que as execuções vão chamar.

    Returns:
        O algoritmo salvo, com id, nome, descrição, código-fonte, ponto de
        entrada e datas de criação e de atualização.
    """
    payload = {
        "name": name,
        "description": description,
        "source_code": source_code,
        "entry_point": entry_point,
    }
    return Algorithm.model_validate(request("POST", "/algorithms", json=payload))


def list_algorithms(limit: int = 50, offset: int = 0) -> list[Algorithm]:
    """Lista os algoritmos salvos no Lambda Lab.

    Devolve os algoritmos em ordem de criação, sem nenhum filtro. Use para
    navegar por eles ou paginá-los; para procurar um algoritmo por nome ou
    descrição, use search_algorithms.

    Args:
        limit: Número máximo de algoritmos a devolver.
        offset: Quantos algoritmos pular, para paginação.

    Returns:
        Os algoritmos encontrados, cada um com id, nome, descrição,
        código-fonte, ponto de entrada e datas de criação e de atualização. A
        lista fica vazia quando o offset passa do último algoritmo.
    """
    payload = request("GET", "/algorithms", params={"limit": limit, "offset": offset})
    return [Algorithm.model_validate(item) for item in payload]


def search_algorithms(
    name: Optional[str] = None,
    description: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Algorithm]:
    """Busca algoritmos salvos por nome ou descrição.

    Os filtros se combinam com E (AND), então passar os dois restringe o
    resultado. Ambos buscam um trecho do texto, sem diferenciar maiúsculas de
    minúsculas, então "fib" encontra "fibonacci_dp". Sem nenhum filtro,
    devolve todos os algoritmos, exatamente como list_algorithms. Use para
    encontrar um algoritmo que já resolva o problema antes de escrever um novo.

    Args:
        name: Texto a procurar em qualquer parte do nome do algoritmo.
        description: Texto a procurar em qualquer parte da descrição.
        limit: Número máximo de algoritmos a devolver.
        offset: Quantos algoritmos pular, para paginação.

    Returns:
        Os algoritmos encontrados, cada um com id, nome, descrição,
        código-fonte, ponto de entrada e datas de criação e de atualização. A
        lista fica vazia quando nada corresponde.
    """
    filters = {"name": name, "description": description}
    payload = request(
        "GET",
        "/algorithms/search",
        params=compose_search_params(filters, limit, offset),
    )
    return [Algorithm.model_validate(item) for item in payload]


def get_algorithm(algorithm_id: int) -> Algorithm:
    """Obtém um algoritmo salvo pelo id, com o código-fonte completo.

    Use para ler o código de um algoritmo antes de executá-lo ou corrigi-lo. A
    ferramenta falha com "algorithm not found" quando o id não existe.

    Args:
        algorithm_id: Id do algoritmo, como devolvido por create_algorithm.

    Returns:
        O algoritmo, com id, nome, descrição, código-fonte, ponto de entrada e
        datas de criação e de atualização.
    """
    return Algorithm.model_validate(request("GET", f"/algorithms/{algorithm_id}"))


def execute_algorithm(
    algorithm_id: int,
    arguments: Optional[dict[str, Any]] = None,
) -> Execution:
    """Executa um algoritmo salvo com os argumentos dados e espera o resultado.

    A execução roda em segundo plano, e esta ferramenta espera até 5 segundos
    que ela termine. A maioria das execuções termina nesse tempo e volta como
    completed, failed ou timed_out, com os mesmos campos de get_execution
    (result, stdout, error, duration_in_ms e peak_memory_in_kb), então não é
    preciso chamar get_execution. Uma execução mais lenta volta ainda pending
    ou running: nesse caso, chame get_execution com o id dela até que termine.
    Cada chamada executa o algoritmo de novo: os resultados nunca vão para
    cache.

    Args:
        algorithm_id: Id do algoritmo a executar, como devolvido por
            create_algorithm.
        arguments: Argumentos nomeados do ponto de entrada, em um objeto cujas
            chaves são os nomes dos parâmetros, por exemplo {"n": 10} para
            solve(n). Deixe vazio quando o ponto de entrada não recebe
            parâmetros.

    Returns:
        A execução, terminada ou ainda em andamento, com os mesmos campos de
        get_execution.
    """
    payload = {"arguments": arguments or {}}
    execution = Execution.model_validate(
        request("POST", f"/algorithms/{algorithm_id}/executions", json=payload)
    )

    deadline = time.monotonic() + _EXECUTION_WAIT_IN_SECONDS
    while execution.status in _UNFINISHED_STATUSES and time.monotonic() < deadline:
        time.sleep(_EXECUTION_POLL_INTERVAL_IN_SECONDS)
        execution = Execution.model_validate(
            request("GET", f"/executions/{execution.id}")
        )

    return execution


def get_execution(execution_id: int) -> Execution:
    """Monitora uma execução: o status e, ao terminar, resultado, tempo e memória.

    O status vai de pending para running e termina como completed, failed ou
    timed_out. Enquanto estiver pending ou running, chame esta ferramenta de
    novo. Uma execução terminada nunca muda. A ferramenta falha com
    "execution not found" quando o id não existe.

    Além do status, a execução informa:
    - result: o valor devolvido pelo ponto de entrada, só quando completed.
      Valores que não são JSON, como sets ou inteiros com milhares de dígitos,
      vêm como a string do seu repr;
    - stdout: o que o algoritmo imprimiu, cortado após 10.000 caracteres;
    - error: o traceback quando failed, ou a mensagem de tempo esgotado quando
      timed_out;
    - duration_in_ms: tempo gasto dentro da chamada ao ponto de entrada. Em
      execuções timed_out, o tempo de relógio até ela ser interrompida;
    - elapsed_in_ms: tempo desde o início da execução, só enquanto running;
    - peak_memory_in_kb: pico de memória residente do processo inteiro,
      incluindo cerca de 9 MB do próprio interpretador. Vazio quando
      timed_out;
    - datas e horas em started_at, finished_at e created_at.

    Args:
        execution_id: Id da execução, como devolvido por execute_algorithm.

    Returns:
        A execução, com id, algorithm_id, arguments, status, result, stdout,
        error, tempos, pico de memória e datas.
    """
    return Execution.model_validate(request("GET", f"/executions/{execution_id}"))


def list_executions(limit: int = 50, offset: int = 0) -> list[Execution]:
    """Lista as execuções de todos os algoritmos do Lambda Lab.

    Devolve as execuções em ordem de criação, sem nenhum filtro. Para filtrar
    por status ou algoritmo, use search_executions; para monitorar uma única
    execução, use get_execution, pois só ela informa elapsed_in_ms.

    Args:
        limit: Número máximo de execuções a devolver.
        offset: Quantas execuções pular, para paginação.

    Returns:
        As execuções encontradas, com os mesmos campos de get_execution. A
        lista fica vazia quando o offset passa da última execução.
    """
    payload = request("GET", "/executions", params={"limit": limit, "offset": offset})
    return [Execution.model_validate(item) for item in payload]


def search_executions(
    status: Optional[ExecutionStatus] = None,
    algorithm_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Execution]:
    """Busca execuções por status ou algoritmo.

    Os filtros se combinam com E (AND) e exigem o valor exato. Use status
    "completed" para obter só as execuções terminadas com sucesso, ou
    algorithm_id para obter o histórico de um algoritmo, por exemplo para
    comparar durações entre entradas. Sem nenhum filtro, devolve todas as
    execuções, exatamente como list_executions.

    Args:
        status: Devolve só as execuções neste status.
        algorithm_id: Devolve só as execuções deste algoritmo.
        limit: Número máximo de execuções a devolver.
        offset: Quantas execuções pular, para paginação.

    Returns:
        As execuções encontradas, com os mesmos campos de get_execution. A
        lista fica vazia quando nada corresponde.
    """
    filters = {"status": status, "algorithm_id": algorithm_id}
    payload = request(
        "GET",
        "/executions/search",
        params=compose_search_params(filters, limit, offset),
    )
    return [Execution.model_validate(item) for item in payload]
