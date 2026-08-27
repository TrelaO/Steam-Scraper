import builtins as _builtins_module
import concurrent.futures
import logging
import sqlite3
import traceback
from typing import Callable

import pandas as pd

from . import llm_etl_generator

logger = logging.getLogger("steam_etl.etl_runner")

MAX_ATTEMPTS = 3
# 30s repeatedly proved too tight against a real ~139k-row dataset even for otherwise-
# correct generated code (a plain Python loop over that many rows adds up); 90s gives
# real headroom while still bounding a truly broken/infinite-loop generation attempt.
EXEC_TIMEOUT_SECONDS = 90

# Generated ETL code may only import these modules. Keeps the sandbox from reaching
# out to the filesystem/network/subprocess even though exec() itself can't be fully sealed.
# Pure data-munging stdlib modules only - nothing that touches I/O, processes, or the network.
ALLOWED_MODULES = {
    "pandas", "json", "re", "datetime", "math", "ast", "time", "itertools",
    "collections", "decimal", "statistics", "string", "numpy",
}

# Denylist rather than allowlist: an allowlist means every ordinary builtin the LLM
# might reasonably use (next(), iter(), type(), getattr()...) has to be predicted and
# added in advance, and missing one just breaks otherwise-correct generated code with
# a NameError. Starting from ALL public builtins and denying only the genuinely
# dangerous ones (file/process/interactive/introspection-of-globals) is more robust -
# note this was never a hardened sandbox against a determined adversary anyway (any
# object's __class__.__mro__ can reach far more than __builtins__ restricts), so this
# is about avoiding accidental misuse, not defeating a deliberate escape attempt.
_UNSAFE_BUILTIN_NAMES = frozenset({
    "open", "eval", "exec", "compile", "__import__", "input", "breakpoint",
    "exit", "quit", "help", "copyright", "credits", "license",
    "globals", "locals", "vars", "dir",
    "setattr", "delattr", "memoryview",
})


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root not in ALLOWED_MODULES:
        raise ImportError(f"Import of '{name}' is not permitted in generated ETL code")
    return __import__(name, globals, locals, fromlist, level)


def _build_sandbox_globals(df: pd.DataFrame, conn: sqlite3.Connection) -> dict:
    safe_builtins = {
        name: getattr(_builtins_module, name)
        for name in dir(_builtins_module)
        if not name.startswith("_") and name not in _UNSAFE_BUILTIN_NAMES
    }
    safe_builtins["__import__"] = _guarded_import
    return {"__builtins__": safe_builtins, "pd": pd, "df": df, "conn": conn}


def _format_generated_code_traceback(exc: BaseException) -> str:
    """Trims the traceback down to just the frames inside the generated code (the
    exec'd string, filename '<string>'), dropping our own ThreadPoolExecutor/sandbox
    plumbing - keeps retry prompts shorter and the signal focused on the LLM's own bug."""
    frames = traceback.extract_tb(exc.__traceback__)
    user_frames = [f for f in frames if f.filename == "<string>"]
    lines = ["Traceback (most recent call last):\n"]
    lines.extend(traceback.format_list(user_frames))
    lines.extend(traceback.format_exception_only(type(exc), exc))
    return "".join(lines).strip()


def _execute_once(code: str, df: pd.DataFrame, conn: sqlite3.Connection) -> dict:
    sandbox = _build_sandbox_globals(df, conn)

    def run():
        exec(code, sandbox)
        if "run_etl" not in sandbox:
            raise RuntimeError("Generated code must define a run_etl(df, conn) function")
        return sandbox["run_etl"](df, conn)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run)
        return future.result(timeout=EXEC_TIMEOUT_SECONDS)


def run_etl_with_retries(
    file_format: str,
    df: pd.DataFrame,
    conn: sqlite3.Connection,
    ddl: str,
    sample: str,
    on_progress: Callable[[list[dict]], None] | None = None,
) -> dict:
    """Generates ETL code via the LLM and executes it, feeding any error back to the
    LLM for a corrected attempt, up to MAX_ATTEMPTS total tries. Calls on_progress
    with the logs-so-far after every attempt, so a caller can surface live status."""
    logs = []

    logger.info("Requesting initial ETL code from Gemini (format=%s, rows=%d)", file_format, len(df))
    code = llm_etl_generator.generate_etl_code(file_format, ddl, sample)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("Executing generated code, attempt %d/%d", attempt, MAX_ATTEMPTS)
        try:
            result = _execute_once(code, df.copy(), conn)
            logs.append({"attempt": attempt, "status": "success", "code": code})
            if on_progress:
                on_progress(list(logs))
            logger.info("Attempt %d succeeded: %s", attempt, result)
            return {"status": "success", "code": code, "logs": logs, "result": result}
        except Exception as exc:
            error_text = _format_generated_code_traceback(exc)
            logs.append({"attempt": attempt, "status": "error", "error": error_text, "code": code})
            if on_progress:
                on_progress(list(logs))
            logger.warning("Attempt %d failed: %s: %s", attempt, exc.__class__.__name__, exc)
            if attempt == MAX_ATTEMPTS:
                logger.error("All %d attempts exhausted, giving up", MAX_ATTEMPTS)
                return {"status": "failed", "code": code, "logs": logs, "error": error_text}
            logger.info("Requesting corrected code from Gemini for attempt %d", attempt + 1)
            code = llm_etl_generator.generate_etl_code(
                file_format, ddl, sample, previous_code=code, previous_error=error_text
            )

    return {"status": "failed", "code": code, "logs": logs}
