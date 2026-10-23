from collections import Counter
from datetime import datetime, timezone
from openai import APIStatusError
from statistics import mean
from typing import Any
import argparse
import asyncio
import json
import os
import time

from services.agent_service import answer_question
from services.judge_service import CRITERIA, JUDGE_MODEL, compose_question, judge_answer
from services.llm_service import (
    LLM_MODEL,
    LLM_REASONING_EFFORT,
    can_retry_request,
    token_usage,
)
from services.tools_service import call_tool


_CASES_PATH = "/app/judge_cases.json"
_REPORT_PATH = "/app/judge_report.json"
_MAX_CASE_ATTEMPTS = 3
_RATE_LIMIT_WAIT_IN_SECONDS = 60
_TOKEN_KINDS = ("input", "output", "reasoning")
_PAYMENT_REQUIRED_STATUS_CODE = 402


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score the agent on the judge cases with an LLM judge. Each "
        "scored case is saved at once, so running again resumes where it stopped."
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="score at most this many of the cases not scored yet",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="discard the existing report and score every case again",
    )
    return parser.parse_args()


def load_cases() -> list[dict[str, Any]]:
    with open(_CASES_PATH, encoding="utf-8") as file:
        return json.load(file)


def compose_configuration() -> dict[str, str]:
    return {
        "agent_model": LLM_MODEL,
        "agent_reasoning_effort": LLM_REASONING_EFFORT,
        "judge_model": JUDGE_MODEL,
    }


def load_report(restart: bool) -> dict[str, Any]:
    configuration = compose_configuration()
    if restart or not os.path.exists(_REPORT_PATH):
        return {"configuration": configuration, "cases": []}

    with open(_REPORT_PATH, encoding="utf-8") as file:
        report = json.load(file)

    # Notas de outra configuração de modelos não se misturam às novas.
    if report["configuration"] != configuration:
        raise SystemExit(
            f"{_REPORT_PATH} was scored with {report['configuration']}, but the "
            f"current setup is {configuration}. Run with --restart to discard it."
        )

    return report


def save_report(report: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    order = [case["id"] for case in cases]
    results = sorted(report["cases"], key=lambda result: order.index(result["id"]))
    content = {
        "configuration": report["configuration"],
        "summary": compose_summary(results, cases),
        "cases": results,
    }

    temporary_path = f"{_REPORT_PATH}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(content, file, ensure_ascii=False, indent=2)
        file.write("\n")

    # O contêiner roda como root; o relatório fica com o dono da pasta.
    folder = os.stat(os.path.dirname(_REPORT_PATH))
    os.chown(temporary_path, folder.st_uid, folder.st_gid)
    os.replace(temporary_path, _REPORT_PATH)


def compose_summary(
    results: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    averages = {
        criterion: round(mean(result["scores"][criterion] for result in results), 2)
        for criterion in CRITERIA
        if results
    }
    if averages:
        averages["overall"] = round(
            mean(averages[criterion] for criterion in CRITERIA), 2
        )

    tokens = {
        phase: {
            kind: sum(result["tokens"][phase][kind] for result in results)
            for kind in _TOKEN_KINDS
        }
        for phase in ("agent", "judge")
    }
    return {
        "scored_cases": len(results),
        "total_cases": len(cases),
        "averages": averages,
        "tokens": tokens,
    }


def measure_tokens(before: Counter[str]) -> dict[str, int]:
    return {kind: token_usage[kind] - before[kind] for kind in _TOKEN_KINDS}


async def score_case(case: dict[str, Any]) -> dict[str, Any]:
    tool_calls = []

    async def record_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool_calls.append(name)
        return await call_tool(name, arguments)

    started_at = time.monotonic()
    tokens_before = token_usage.copy()
    answer, _ = await answer_question(
        compose_question(case),
        [],
        bypass_cache=True,
        tool_caller=record_tool_call,
    )
    agent_tokens = measure_tokens(tokens_before)

    tokens_before = token_usage.copy()
    verdict = await judge_answer(case, answer)
    judge_tokens = measure_tokens(tokens_before)

    return {
        "id": case["id"],
        "difficulty": case["difficulty"],
        "scores": {criterion: verdict[criterion] for criterion in CRITERIA},
        "justification": verdict["justification"],
        "tool_calls": tool_calls,
        "duration_in_seconds": round(time.monotonic() - started_at, 1),
        "tokens": {"agent": agent_tokens, "judge": judge_tokens},
        "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "answer": answer,
    }


async def score_case_with_retries(case: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(1, _MAX_CASE_ATTEMPTS + 1):
        try:
            return await score_case(case)
        except APIStatusError as error:
            if not can_retry_request(error) or attempt == _MAX_CASE_ATTEMPTS:
                raise

            print(
                f"  rate limited ({error.status_code}), waiting "
                f"{_RATE_LIMIT_WAIT_IN_SECONDS}s before attempt {attempt + 1}",
                flush=True,
            )
            await asyncio.sleep(_RATE_LIMIT_WAIT_IN_SECONDS)


def format_tokens(tokens: dict[str, int]) -> str:
    return " / ".join(f"{tokens[kind]:,} {kind}" for kind in _TOKEN_KINDS)


def print_case_result(result: dict[str, Any]) -> None:
    scores = ", ".join(
        f"{criterion} {result['scores'][criterion]}" for criterion in CRITERIA
    )
    print(f"  {scores} | {result['duration_in_seconds']}s")
    print(f"  tools: {', '.join(result['tool_calls']) or 'none'}")
    print(f"  agent tokens: {format_tokens(result['tokens']['agent'])}")
    print(f"  judge tokens: {format_tokens(result['tokens']['judge'])}")
    print(f"  {result['justification']}", flush=True)


def print_summary(report: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    order = [case["id"] for case in cases]
    results = sorted(report["cases"], key=lambda result: order.index(result["id"]))
    summary = compose_summary(results, cases)

    print(f"\n{'case':<32} {'difficulty':<10} {'correct':>7} {'effic':>5} {'clar':>4}")
    for result in results:
        scores = result["scores"]
        print(
            f"{result['id']:<32} {result['difficulty']:<10} "
            f"{scores['correctness']:>7} {scores['efficiency']:>5} {scores['clarity']:>4}"
        )

    averages = summary["averages"]
    if averages:
        print(
            f"{'average':<32} {'':<10} {averages['correctness']:>7} "
            f"{averages['efficiency']:>5} {averages['clarity']:>4}"
            f"   overall {averages['overall']}"
        )

    print(f"\n{summary['scored_cases']} of {summary['total_cases']} cases scored")
    print(f"agent tokens: {format_tokens(summary['tokens']['agent'])}")
    print(f"judge tokens: {format_tokens(summary['tokens']['judge'])}")
    print(f"report: {_REPORT_PATH}")


async def main() -> None:
    arguments = parse_arguments()
    cases = load_cases()
    report = load_report(arguments.restart)

    scored_ids = {result["id"] for result in report["cases"]}
    pending_cases = [case for case in cases if case["id"] not in scored_ids]
    pending_cases = pending_cases[: arguments.limit]
    print(
        f"{len(scored_ids)} of {len(cases)} cases already scored, "
        f"scoring {len(pending_cases)} now with {report['configuration']}"
    )

    stopped = False
    for index, case in enumerate(pending_cases, 1):
        print(
            f"\n[{index}/{len(pending_cases)}] {case['id']} ({case['difficulty']})",
            flush=True,
        )

        try:
            result = await score_case_with_retries(case)
        except Exception as error:
            is_balance_exhausted = (
                isinstance(error, APIStatusError)
                and error.status_code == _PAYMENT_REQUIRED_STATUS_CODE
            )
            print(
                "  stopped: the prepaid Gemini balance is exhausted (402)"
                if is_balance_exhausted
                else f"  stopped: {error}"
            )
            print("  scored cases are saved; run again later to resume")
            stopped = True
            break

        report["cases"].append(result)
        save_report(report, cases)
        print_case_result(result)

    print_summary(report, cases)

    if stopped:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
