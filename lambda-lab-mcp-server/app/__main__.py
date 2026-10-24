from fastmcp import FastMCP

from tools import (
    check_algorithm_service_health,
    create_algorithm,
    execute_algorithm,
    get_algorithm,
    get_execution,
    list_algorithms,
    list_executions,
    search_algorithms,
    search_executions,
    validate_algorithm,
)


mcp = FastMCP(
    "lambda-lab",
    tools=[
        check_algorithm_service_health,
        validate_algorithm,
        create_algorithm,
        list_algorithms,
        search_algorithms,
        get_algorithm,
        execute_algorithm,
        get_execution,
        list_executions,
        search_executions,
    ],
)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=9001)
