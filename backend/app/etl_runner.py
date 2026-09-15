import builtins as _builtins_module
import logging
import multiprocessing as mp
import sqlite3
import traceback
from queue import Empty as _QueueEmpty
from typing import Callable

import pandas as pd

from . import llm_etl_generator

logger = logging.getLogger("steam_etl.etl_runner")

MAX_ATTEMPTS = 3
# 30s, then 90s, both repeatedly proved too tight against a real ~139k-row dataset -
# even generated code that correctly batches every DB write via executemany() (see
# the timeout-specific retry prompt in llm_etl_generator._build_prompt) still does
# several pure-Python passes over every row to parse/normalize values first, and
# that parsing - not the DB writes - is what actually dominates at this scale. Safe
# to be generous here: unlike a thread-based timeout, a subprocess that runs past
# this limit is genuinely killed (process.terminate()/kill() in _execute_once), not
# just abandoned - a longer bound doesn't risk anything hanging around.
EXEC_TIMEOUT_SECONDS = 240

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

# Generated code runs in a genuinely separate OS process (see _execute_once), spawned
# rather than forked - this process also runs a multi-threaded FastAPI/uvicorn server
# plus its own background threading.Thread per ETL job, and forking a multi-threaded
# process only duplicates the forking thread, leaving any locks other threads held at
# fork time in an unrecoverable state in the child. spawn starts a clean interpreter
# instead, at the cost of re-importing this module and pickling the arguments.
_MP_CONTEXT = mp.get_context("spawn")


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
    exec'd string, filename '<string>'), dropping our own subprocess/sandbox plumbing
    - keeps retry prompts shorter and the signal focused on the LLM's own bug."""
    frames = traceback.extract_tb(exc.__traceback__)
    user_frames = [f for f in frames if f.filename == "<string>"]
    lines = ["Traceback (most recent call last):\n"]
    lines.extend(traceback.format_list(user_frames))
    lines.extend(traceback.format_exception_only(type(exc), exc))
    return "".join(lines).strip()


class _ChildExecutionError(RuntimeError):
    """Carries a traceback already formatted inside the child process by
    _format_generated_code_traceback - the original traceback object can't cross the
    process boundary, so the formatted text is what's sent back on the result queue.
    Callers should use str(exc) directly rather than re-formatting this one."""


def _child_entry(code: str, df: pd.DataFrame, result_queue: "mp.Queue") -> None:
    """Runs entirely inside the spawned child process: opens its OWN connection to
    the warehouse (imported locally - this only ever runs in the child, and importing
    here avoids any import-time coupling between etl_runner and db at module load),
    execs the generated code, and commits or rolls back before exiting. Unlike the
    previous thread-based version, the generated code no longer shares the caller's
    connection/transaction - it must be self-contained, because if this process gets
    killed for running past EXEC_TIMEOUT_SECONDS, nothing else survives it either."""
    from . import db

    conn = db.get_connection()
    try:
        sandbox = _build_sandbox_globals(df, conn)
        exec(code, sandbox)
        if "run_etl" not in sandbox:
            raise RuntimeError("Generated code must define a run_etl(df, conn) function")
        result = sandbox["run_etl"](df, conn)
        conn.commit()
        result_queue.put(("success", result))
    except Exception as exc:
        conn.rollback()
        result_queue.put(("error", _format_generated_code_traceback(exc)))
    finally:
        conn.close()


HEARTBEAT_INTERVAL_SECONDS = 4


def _execute_once(
    code: str,
    df: pd.DataFrame,
    on_heartbeat: Callable[[int], None] | None = None,
) -> dict:
    result_queue = _MP_CONTEXT.Queue()
    process = _MP_CONTEXT.Process(target=_child_entry, args=(code, df, result_queue), daemon=True)
    process.start()

    elapsed = 0
    while True:
        process.join(timeout=HEARTBEAT_INTERVAL_SECONDS)
        if not process.is_alive():
            break
        elapsed += HEARTBEAT_INTERVAL_SECONDS
        if elapsed >= EXEC_TIMEOUT_SECONDS:
            # terminate() (SIGTERM) first, kill() (SIGKILL) only if it ignores that -
            # this is what future.result(timeout=...) could never do to a thread: a
            # hung/infinite-looping generated script is actually stopped, not just
            # abandoned while it keeps running in the background.
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            raise TimeoutError(f"Generated code did not finish within {EXEC_TIMEOUT_SECONDS}s")
        if on_heartbeat:
            on_heartbeat(elapsed)

    try:
        status, payload = result_queue.get(timeout=5)
    except _QueueEmpty:
        # The process exited without putting anything on the queue - a hard crash
        # (segfault, OOM kill) rather than a normal Python exception reaching us.
        raise RuntimeError(
            f"Generated code's process exited unexpectedly (exit code {process.exitcode}) "
            "without an error message - likely an out-of-memory kill on a large dataset."
        )
    if status == "error":
        raise _ChildExecutionError(payload)
    return payload


def run_etl_with_retries(
    file_format: str,
    df: pd.DataFrame,
    ddl: str,
    sample: str,
    on_progress: Callable[[list[dict]], None] | None = None,
    on_step: Callable[[str], None] | None = None,
) -> dict:
    """Generates ETL code via the LLM and executes it, feeding any error back to the
    LLM for a corrected attempt, up to MAX_ATTEMPTS total tries. Calls on_progress
    with the logs-so-far after every attempt, and on_step with a short human-readable
    status line at every meaningful transition (including execution heartbeats), so a
    caller can surface live status instead of a silent gap while code runs."""
    logs = []

    def step(msg: str) -> None:
        logger.info(msg)
        if on_step:
            on_step(msg)

    step(f"Requesting initial ETL code from Gemini (format={file_format}, rows={len(df)})...")
    code = llm_etl_generator.generate_etl_code(file_format, ddl, sample)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        step(f"Executing generated code, attempt {attempt}/{MAX_ATTEMPTS}...")
        try:
            result = _execute_once(
                code, df,
                on_heartbeat=lambda s, a=attempt: step(
                    f"Still executing, attempt {a}/{MAX_ATTEMPTS}... {s}s elapsed"
                ),
            )
            logs.append({"attempt": attempt, "status": "success", "code": code})
            if on_progress:
                on_progress(list(logs))
            step(f"Attempt {attempt} succeeded: {result}")

            mapping = None
            try:
                step("Asking Gemini to summarize the field mapping it used...")
                mapping = llm_etl_generator.explain_mapping(code, ddl)
            except Exception as exc:
                # Purely explanatory/enrichment info for the UI - a failure here
                # (quota, malformed JSON, network) shouldn't fail an otherwise-
                # successful ETL run.
                logger.warning("Field-mapping summary failed (non-fatal): %s", exc)

            return {
                "status": "success", "code": code, "logs": logs, "result": result, "mapping": mapping,
            }
        except Exception as exc:
            error_text = (
                str(exc) if isinstance(exc, _ChildExecutionError)
                else _format_generated_code_traceback(exc)
            )
            logs.append({"attempt": attempt, "status": "error", "error": error_text, "code": code})
            if on_progress:
                on_progress(list(logs))
            step(f"Attempt {attempt} failed: {exc.__class__.__name__}: {exc}")
            if attempt == MAX_ATTEMPTS:
                logger.error("All %d attempts exhausted, giving up", MAX_ATTEMPTS)
                return {"status": "failed", "code": code, "logs": logs, "error": error_text}
            step(f"Requesting corrected code from Gemini for attempt {attempt + 1}...")
            code = llm_etl_generator.generate_etl_code(
                file_format, ddl, sample, previous_code=code, previous_error=error_text,
                previous_error_was_timeout=isinstance(exc, TimeoutError),
            )

    return {"status": "failed", "code": code, "logs": logs}
