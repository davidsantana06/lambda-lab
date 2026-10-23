from datetime import datetime, timezone
from sqlmodel import Session
from typing import Any
import ast
import json
import os
import pwd
import signal
import subprocess
import sys
import tempfile
import time

from database import engine
from models import Algorithm, Execution
from schemas import AlgorithmValidation, ExecutionRead


_EXECUTION_TIMEOUT_IN_SECONDS = 10
_EXECUTION_MEMORY_LIMIT_IN_MB = 256
_EXECUTION_OUTPUT_LIMIT_IN_CHARS = 10_000
_EXECUTION_USER = "nobody"
_EXECUTION_PATH = "/usr/local/bin:/usr/bin:/bin"
_REPORT_FIELDS = (
    "status",
    "result",
    "stdout",
    "error",
    "duration_in_ms",
    "peak_memory_in_kb",
)

# Script do processo filho; o relatório sai por uma cópia do stdout, longe dos prints.
_RUNNER_SOURCE_CODE = r"""
import contextlib
import io
import json
import linecache
import os
import resource
import sys
import time
import traceback


# Novo fork para que o getrusage não herde o pico de memória do serviço.
worker_pid = os.fork()
if worker_pid:
    _, wait_status = os.waitpid(worker_pid, 0)
    exit_code = os.waitstatus_to_exitcode(wait_status)
    os._exit(exit_code if exit_code >= 0 else 128 - exit_code)

payload = json.load(sys.stdin)
memory_limit_in_bytes = payload["memory_limit_in_bytes"]
resource.setrlimit(resource.RLIMIT_AS, (memory_limit_in_bytes, memory_limit_in_bytes))
sys.set_int_max_str_digits(0)

report_stream = os.fdopen(os.dup(1), "w", encoding="utf-8")
os.dup2(2, 1)

source_code = payload["source_code"]
linecache.cache["algorithm.py"] = (
    len(source_code),
    None,
    source_code.splitlines(True),
    "algorithm.py",
)
namespace = {"__name__": "algorithm"}
captured_stdout = io.StringIO()
report = {"status": "failed", "result": None, "error": None, "duration_in_ms": None}

try:
    with contextlib.redirect_stdout(captured_stdout):
        exec(compile(source_code, "algorithm.py", "exec"), namespace)
        entry_point = namespace[payload["entry_point"]]

        started_at = time.perf_counter_ns()
        try:
            report["result"] = entry_point(**payload["arguments"])
        finally:
            elapsed_in_ns = time.perf_counter_ns() - started_at
            report["duration_in_ms"] = round(elapsed_in_ns / 1_000_000, 3)

    report["status"] = "completed"
except BaseException as error:
    frames = traceback.extract_tb(error.__traceback__)
    while frames and frames[0].filename != "algorithm.py":
        frames.pop(0)

    lines = traceback.format_list(frames)
    if lines:
        lines.insert(0, "Traceback (most recent call last):\n")

    lines.extend(traceback.format_exception_only(error))
    report["error"] = "".join(lines)

report["peak_memory_in_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

stdout = captured_stdout.getvalue()
stdout_limit_in_chars = payload["stdout_limit_in_chars"]
if len(stdout) > stdout_limit_in_chars:
    stdout = stdout[:stdout_limit_in_chars] + "\n[stdout truncated]"

report["stdout"] = stdout

# Com o limite padrão de dígitos de volta, inteiros longos demais caem no repr.
sys.set_int_max_str_digits(sys.int_info.default_max_str_digits)
try:
    report_text = json.dumps(report, allow_nan=False)
except (TypeError, ValueError, RecursionError):
    sys.set_int_max_str_digits(0)
    report["result"] = repr(report["result"])
    report_text = json.dumps(report)

report_stream.write(report_text)
report_stream.flush()
os._exit(0)
"""


def validate_source_code(source_code: str, entry_point: str) -> AlgorithmValidation:
    try:
        tree = ast.parse(source_code, filename="algorithm.py")
        compile(tree, "algorithm.py", "exec")
    except SyntaxError as error:
        return AlgorithmValidation(
            valid=False,
            line=error.lineno,
            column=error.offset,
            message=error.msg,
        )
    except ValueError as error:
        return AlgorithmValidation(valid=False, message=str(error))

    is_defined = any(
        isinstance(node, ast.FunctionDef) and node.name == entry_point
        for node in tree.body
    )
    if not is_defined:
        return AlgorithmValidation(
            valid=False,
            message=f"entry point {entry_point!r} is not a module-level function",
        )

    return AlgorithmValidation(valid=True)


def run_execution(execution_id: int) -> None:
    with Session(engine) as session:
        execution = session.get(Execution, execution_id)
        algorithm = session.get(Algorithm, execution.algorithm_id)

        execution.status = "running"
        execution.started_at = datetime.now(timezone.utc)
        session.add(execution)
        session.commit()

        try:
            report = _run_algorithm(algorithm, execution.arguments)
        except Exception as error:
            report = {
                "status": "failed",
                "error": f"could not start the execution: {error}",
            }

        for field in _REPORT_FIELDS:
            setattr(execution, field, report.get(field))

        execution.finished_at = datetime.now(timezone.utc)
        session.add(execution)
        session.commit()


def monitor_execution(execution: Execution) -> ExecutionRead:
    monitoring = ExecutionRead.model_validate(execution)
    if execution.status == "running" and execution.started_at is not None:
        started_at = execution.started_at.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - started_at
        monitoring.elapsed_in_ms = round(elapsed.total_seconds() * 1000, 3)

    return monitoring


def _run_algorithm(algorithm: Algorithm, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps(
        {
            "source_code": algorithm.source_code,
            "entry_point": algorithm.entry_point,
            "arguments": arguments,
            "memory_limit_in_bytes": _EXECUTION_MEMORY_LIMIT_IN_MB * 1024 * 1024,
            "stdout_limit_in_chars": _EXECUTION_OUTPUT_LIMIT_IN_CHARS,
        }
    )

    user = pwd.getpwnam(_EXECUTION_USER)
    with tempfile.TemporaryDirectory(prefix="execution-") as directory:
        os.chown(directory, user.pw_uid, user.pw_gid)

        started_at = time.perf_counter()
        with subprocess.Popen(
            [sys.executable, "-I", "-X", "utf8", "-c", _RUNNER_SOURCE_CODE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=directory,
            env={"PATH": _EXECUTION_PATH, "HOME": directory, "TMPDIR": directory},
            user=user.pw_uid,
            group=user.pw_gid,
            extra_groups=[],
            process_group=0,
        ) as process:
            try:
                stdout, stderr = process.communicate(
                    payload.encode(),
                    timeout=_EXECUTION_TIMEOUT_IN_SECONDS,
                )
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

                wall_clock_in_ms = (time.perf_counter() - started_at) * 1000
                return {
                    "status": "timed_out",
                    "duration_in_ms": round(wall_clock_in_ms, 3),
                    "error": f"execution timed out after {_EXECUTION_TIMEOUT_IN_SECONDS} seconds",
                }

    return _compose_report(process.returncode, stdout, stderr)


def _compose_report(return_code: int, stdout: bytes, stderr: bytes) -> dict[str, Any]:
    try:
        return json.loads(stdout)
    except ValueError:
        error = stderr.decode(errors="replace").strip()
        return {
            "status": "failed",
            "error": error[-_EXECUTION_OUTPUT_LIMIT_IN_CHARS:]
            or f"execution exited with code {return_code} without a report",
        }
