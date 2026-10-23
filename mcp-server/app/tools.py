from typing import Any, Optional

from client import compose_search_params, request
from models import Algorithm, AlgorithmValidation, Execution, ExecutionStatus


def check_algorithm_service_health() -> dict[str, str]:
    """Check that the algorithm service is reachable and answering requests.

    Use this to tell a service outage apart from a search that simply found
    nothing, or when other tools keep failing to reach the service.

    Returns:
        The reported status, such as {"status": "ok", "service": "algorithm"}.
    """
    return request("GET", "/health")


def validate_algorithm(
    source_code: str,
    entry_point: str = "solve",
) -> AlgorithmValidation:
    """Check an algorithm's source code without saving or running it.

    Parses the Python source code and checks that the entry point is a plain
    function defined at module level, not nested, async or a lambda. Use this
    before create_algorithm to catch syntax errors early. The code is not run,
    so runtime errors only show up in an execution.

    The result has valid set to true when the code is ready to be saved.
    Otherwise valid is false and message explains the problem, with the
    1-based line and column of a syntax error. Line and column are empty when
    the problem is a missing entry point.

    Args:
        source_code: Complete Python 3.12 module that defines the entry point.
        entry_point: Name of the function that executions will call.

    Returns:
        The validation result, with valid, line, column and message.
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
    """Save a new algorithm so that it can be executed.

    The source code is validated first, exactly like validate_algorithm, and
    nothing is saved when it is invalid: the tool fails with the line, column
    and message of the error. Saved algorithms can never be edited or deleted,
    so fixing one means creating a new algorithm, such as "two_sum_v2". On
    success, it returns the saved algorithm with the id that
    execute_algorithm needs.

    The code must follow the execution contract:
    - executions call the entry point with keyword arguments only, as in
      solve(**arguments), so its parameter names must match those keys;
    - the entry point returns the result, and prints are kept apart in the
      execution's stdout, so print only for diagnostics;
    - return JSON values (numbers, strings, booleans, None, lists, and dicts
      with string keys); anything else, such as a set, comes back as its repr;
    - rely on the Python standard library only;
    - module-level code runs once before the call and is not timed, and
      blocks guarded by if __name__ == "__main__" never run;
    - each execution has a 10-second timeout and a 256 MB memory limit.

    Args:
        name: Short identifier of the algorithm, such as "fibonacci_dp".
        description: Problem the algorithm solves and the strategy it uses,
            such as "Fibonacci numbers by bottom-up dynamic programming".
        source_code: Complete Python 3.12 module that defines the entry point.
        entry_point: Name of the function that executions will call.

    Returns:
        The saved algorithm, with its id, name, description, source code,
        entry point and timestamps.
    """
    payload = {
        "name": name,
        "description": description,
        "source_code": source_code,
        "entry_point": entry_point,
    }
    return Algorithm.model_validate(request("POST", "/algorithms", json=payload))


def list_algorithms(limit: int = 50, offset: int = 0) -> list[Algorithm]:
    """List the algorithms saved in Lambda Lab.

    Returns algorithms in creation order, without any filtering. Use this to
    browse them or page through them; use search_algorithms instead when
    looking for an algorithm by name or description.

    Args:
        limit: Maximum number of algorithms to return.
        offset: How many algorithms to skip, for pagination.

    Returns:
        The algorithms found, each with its id, name, description, source
        code, entry point and timestamps. Empty when the offset goes past the
        last algorithm.
    """
    payload = request("GET", "/algorithms", params={"limit": limit, "offset": offset})
    return [Algorithm.model_validate(item) for item in payload]


def search_algorithms(
    name: Optional[str] = None,
    description: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Algorithm]:
    """Search saved algorithms by name or description.

    Filters combine with AND, so passing both narrows the result. Both are
    case-insensitive partial matches, so "fib" matches "fibonacci_dp". Omitting
    every filter returns all algorithms, exactly like list_algorithms. Use this
    to find an algorithm that already solves a problem before writing a new one.

    Args:
        name: Text to look for anywhere in the algorithm name.
        description: Text to look for anywhere in the description.
        limit: Maximum number of algorithms to return.
        offset: How many algorithms to skip, for pagination.

    Returns:
        The matching algorithms, each with its id, name, description, source
        code, entry point and timestamps. Empty when nothing matches.
    """
    filters = {"name": name, "description": description}
    payload = request(
        "GET",
        "/algorithms/search",
        params=compose_search_params(filters, limit, offset),
    )
    return [Algorithm.model_validate(item) for item in payload]


def get_algorithm(algorithm_id: int) -> Algorithm:
    """Get one saved algorithm by its id, including the full source code.

    Use this to read the code of an algorithm before running or fixing it. The
    tool fails with "algorithm not found" when the id does not exist.

    Args:
        algorithm_id: Id of the algorithm, as returned by create_algorithm.

    Returns:
        The algorithm with its id, name, description, source code, entry point
        and timestamps.
    """
    return Algorithm.model_validate(request("GET", f"/algorithms/{algorithm_id}"))


def execute_algorithm(
    algorithm_id: int,
    arguments: Optional[dict[str, Any]] = None,
) -> Execution:
    """Start a new execution of a saved algorithm with the given arguments.

    The execution runs in the background, so this returns at once with status
    "pending" and the execution id. Then call get_execution with that id until
    the status is completed, failed or timed_out. Every call runs the
    algorithm again: results are never cached.

    Args:
        algorithm_id: Id of the algorithm to run, as returned by
            create_algorithm.
        arguments: Keyword arguments for the entry point, as an object whose
            keys are its parameter names, such as {"n": 10} for solve(n).
            Leave it empty when the entry point takes no parameters.

    Returns:
        The new execution, with its id, algorithm_id, arguments and status
        "pending".
    """
    payload = {"arguments": arguments or {}}
    return Execution.model_validate(
        request("POST", f"/algorithms/{algorithm_id}/executions", json=payload)
    )


def get_execution(execution_id: int) -> Execution:
    """Monitor one execution: its status and, once finished, result, time and memory.

    The status goes from pending to running and ends as completed, failed or
    timed_out. While it is pending or running, call this tool again. A finished
    execution never changes. The tool fails with "execution not found" when
    the id does not exist.

    Besides the status, the execution reports:
    - result: the entry point's return value, only when completed. Values that
      are not JSON, such as sets or integers with thousands of digits, come as
      their repr string;
    - stdout: what the algorithm printed, cut after 10,000 characters;
    - error: the traceback when failed, or the timeout message when timed_out;
    - duration_in_ms: time spent inside the entry-point call. For timed_out
      executions, the wall-clock time until it was stopped;
    - elapsed_in_ms: time since the execution started, only while running;
    - peak_memory_in_kb: peak resident memory of the whole process, including
      about 9 MB of interpreter baseline. Empty when timed_out;
    - started_at, finished_at and created_at timestamps.

    Args:
        execution_id: Id of the execution, as returned by execute_algorithm.

    Returns:
        The execution with its id, algorithm_id, arguments, status, result,
        stdout, error, timings, peak memory and timestamps.
    """
    return Execution.model_validate(request("GET", f"/executions/{execution_id}"))


def list_executions(limit: int = 50, offset: int = 0) -> list[Execution]:
    """List the executions of every algorithm in Lambda Lab.

    Returns executions in creation order, without any filtering. Use
    search_executions instead to filter by status or algorithm, and
    get_execution to monitor a single execution, since elapsed_in_ms is only
    reported there.

    Args:
        limit: Maximum number of executions to return.
        offset: How many executions to skip, for pagination.

    Returns:
        The executions found, with the same fields as get_execution. Empty
        when the offset goes past the last execution.
    """
    payload = request("GET", "/executions", params={"limit": limit, "offset": offset})
    return [Execution.model_validate(item) for item in payload]


def search_executions(
    status: Optional[ExecutionStatus] = None,
    algorithm_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Execution]:
    """Search executions by status or algorithm.

    Filters combine with AND and are exact matches. Use status "completed" to
    get only successful finished runs, or algorithm_id to get the history of
    one algorithm, such as to compare durations across inputs. Omitting every
    filter returns all executions, exactly like list_executions.

    Args:
        status: Return only executions in this status.
        algorithm_id: Return only executions of this algorithm.
        limit: Maximum number of executions to return.
        offset: How many executions to skip, for pagination.

    Returns:
        The matching executions, with the same fields as get_execution. Empty
        when nothing matches.
    """
    filters = {"status": status, "algorithm_id": algorithm_id}
    payload = request(
        "GET",
        "/executions/search",
        params=compose_search_params(filters, limit, offset),
    )
    return [Execution.model_validate(item) for item in payload]
