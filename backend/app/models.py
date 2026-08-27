from typing import Any, Optional

from pydantic import BaseModel


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    detected_format: str


class ETLAttemptLog(BaseModel):
    attempt: int
    status: Optional[str] = None
    error: Optional[str] = None
    code: Optional[str] = None


class ETLJobStatus(BaseModel):
    job_id: str
    file_id: str
    status: str
    generated_code: Optional[str] = None
    logs: list[ETLAttemptLog] = []
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    current_step: Optional[str] = None
