import builtins as _builtins_module
import concurrent.futures
import sqlite3
import traceback

import pandas as pd

from . import llm_etl_generator

MAX_ATTEMPTS = 3
EXEC_TIMEOUT_SECONDS = 30

# Generated ETL code may only import these modules. Keeps the sandbox from reaching
# out to the filesystem/network/subprocess even though exec() itself can't be fully sealed.
ALLOWED_MODULES = {"pandas", "json", "re", "datetime", "math"}

_SAFE_BUILTIN_NAMES = (
    "len", "range", "enumerate", "list", "dict", "set", "tuple", "str", "int",
    "float", "bool", "min", "max", "sum", "sorted", "zip", "map", "filter",
    "isinstance", "print", "Exception", "ValueError", "TypeError", "KeyError",
    "StopIteration", "abs", "round", "any", "all", "None", "True", "False",
)


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root not in ALLOWED_MODULES:
        raise ImportError(f"Import of '{name}' is not permitted in generated ETL code")
    return __import__(name, globals, locals, fromlist, level)


def _build_sandbox_globals(df: pd.DataFrame, conn: sqlite3.Connection) -> dict:
    safe_builtins = {name: getattr(_builtins_module, name) for name in _SAFE_BUILTIN_NAMES}
    safe_builtins["__import__"] = _guarded_import
    return {"__builtins__": safe_builtins, "pd": pd, "df": df, "conn": conn}


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
) -> dict:
    """Generates ETL code via the LLM and executes it, feeding any error back to the
    LLM for a corrected attempt, up to MAX_ATTEMPTS total tries."""
    logs = []
    code = llm_etl_generator.generate_etl_code(file_format, ddl, sample)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = _execute_once(code, df.copy(), conn)
            logs.append({"attempt": attempt, "status": "success", "code": code})
            return {"status": "success", "code": code, "logs": logs, "result": result}
        except Exception as exc:
            error_text = f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc()}"
            logs.append({"attempt": attempt, "status": "error", "error": error_text, "code": code})
            if attempt == MAX_ATTEMPTS:
                return {"status": "failed", "code": code, "logs": logs, "error": error_text}
            code = llm_etl_generator.generate_etl_code(
                file_format, ddl, sample, previous_code=code, previous_error=error_text
            )

    return {"status": "failed", "code": code, "logs": logs}
