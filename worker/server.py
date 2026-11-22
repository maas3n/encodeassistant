from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from .media import Cancelled, SAFE_JOB_NAME
from .workflow import Workflow

MEDIA_TYPES = {".mkv", ".mp4", ".m2ts", ".mts", ".mov", ".avi", ".ts", ".webm"}
SAFE_FILE_NAME = re.compile(r"^(?:comparison-[a-z0-9.-]+-\d+\.png|video\.mkv|crf-[\d.]+\.mkv|movie\.avs)$")


class JobRequest(BaseModel):
    source: str = Field(min_length=1, max_length=1024)
    tuning_kbps: int = Field(gt=0)
    expected_kbps: int = Field(gt=0)
    crop: list[int] | None = Field(default=None, min_length=4, max_length=4)
    scan: Literal["auto", "progressive", "tff", "bff"] = "auto"
    full_encode: bool = False

    @model_validator(mode="after")
    def check_rates(self):
        if self.tuning_kbps >= self.expected_kbps:
            raise ValueError("Two-pass tuning bitrate must be below the expected final bitrate.")
        return self


class Job:
    def __init__(self, directory: Path, request: JobRequest):
        self.directory = directory
        self.request = request
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.state = {
            "id": directory.name, "source": request.source, "status": "queued",
            "stage": "queued", "message": "Waiting for the encoding worker", "progress": 0,
        }

    def update(self, **fields):
        with self.lock:
            self.state.update(fields)
            path = self.directory / "job.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
            temporary.replace(path)

    def snapshot(self):
        with self.lock:
            return self.state.copy()


def create_app(library: Path, work: Path, token: str | None = None) -> FastAPI:
    library, work = library.resolve(), work.resolve()
    if not library.is_dir():
        raise ValueError("The configured source library must be an existing directory.")
    work.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Encode Assistant", version="0.1.0")
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="encode")
    active: dict[str, Job] = {}
    jobs_lock = threading.Lock()
    for stale in work.glob("*/job.json"):
        try:
            data = json.loads(stale.read_text(encoding="utf-8"))
            if data["status"] in ("queued", "running", "cancelling"):
                data.update(status="interrupted", message="The worker restarted before this job finished.")
                stale.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError, KeyError):
            continue

    def authorize(authorization: str | None = Header(default=None)):
        if token and not hmac.compare_digest(
            (authorization or "").encode("utf-8"), f"Bearer {token}".encode("utf-8")
        ):
            raise HTTPException(401, "The worker token is missing or incorrect.")

    def source_path(name: str) -> Path:
        path = (library / name).resolve()
        if not path.is_relative_to(library) or path.is_relative_to(work):
            raise HTTPException(404, "Source file not found.")
        if not path.is_file() or path.suffix.lower() not in MEDIA_TYPES:
            raise HTTPException(404, "Source file not found.")
        return path

    def job_dir(job_id: str) -> Path:
        if not SAFE_JOB_NAME.fullmatch(job_id) or not (work / job_id / "job.json").is_file():
            raise HTTPException(404, "Job not found.")
        return work / job_id

    def run(job: Job, path: Path):
        try:
            job.update(status="running")
            report = Workflow(job, path).run()
            if job.cancelled.is_set():
                raise Cancelled()
            job.update(status="completed", progress=1, stage="completed",
                       message=report.get("message", "Encoding recommendation ready"), report=report)
        except Cancelled:
            job.update(status="cancelled", stage="cancelled", message="The job was cancelled.")
        except Exception as error:
            job.update(status="failed", stage="failed", message=str(error))
        finally:
            with jobs_lock:
                active.pop(job.directory.name, None)

    @app.get("/health", dependencies=[Depends(authorize)])
    def health():
        return {"status": "ok", "api_configured": bool(os.environ.get("OPENAI_API_KEY"))}

    @app.get("/sources", dependencies=[Depends(authorize)])
    def list_sources():
        files = []
        for entry in library.rglob("*"):
            if entry.suffix.lower() in MEDIA_TYPES and entry.is_file():
                resolved = entry.resolve()
                if resolved.is_relative_to(library) and not resolved.is_relative_to(work):
                    files.append(entry.relative_to(library).as_posix())
        return {"sources": sorted(files, key=str.casefold)}

    @app.get("/jobs", dependencies=[Depends(authorize)])
    def list_jobs():
        states = []
        for file in sorted(work.glob("*/job.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                states.append(json.loads(file.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return {"jobs": states[:25]}

    @app.post("/jobs", status_code=202, dependencies=[Depends(authorize)])
    def create_job(request: JobRequest):
        path = source_path(request.source)
        if not os.environ.get("OPENAI_API_KEY"):
            raise HTTPException(409, "Set OPENAI_API_KEY on the worker before creating a job.")
        with jobs_lock:
            if active:
                raise HTTPException(409, "The worker is already running an encoding job.")
            job_id = uuid4().hex[:12]
            directory = work / job_id
            directory.mkdir()
            job = Job(directory, request)
            job.update()
            active[job_id] = job
            pool.submit(run, job, path)
        return job.snapshot()

    @app.get("/jobs/{job_id}", dependencies=[Depends(authorize)])
    def read_job(job_id: str):
        return json.loads((job_dir(job_id) / "job.json").read_text(encoding="utf-8"))

    @app.post("/jobs/{job_id}/cancel", status_code=202, dependencies=[Depends(authorize)])
    def cancel_job(job_id: str):
        job_dir(job_id)
        with jobs_lock:
            job = active.get(job_id)
            if job is None:
                raise HTTPException(409, "The job has already ended.")
            job.cancelled.set()
            job.update(status="cancelling", message="Cancelling the job")
        return job.snapshot()

    @app.get("/jobs/{job_id}/files/{name}", dependencies=[Depends(authorize)])
    def get_file(job_id: str, name: str):
        directory = job_dir(job_id)
        path = directory / name
        if not SAFE_FILE_NAME.fullmatch(name) or not path.is_file():
            raise HTTPException(404, "Output file not found.")
        state = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        if state.get("status") != "completed":
            raise HTTPException(409, "The output is still being generated.")
        return FileResponse(path, filename=name)

    return app


def add_server_arguments(parser: argparse.ArgumentParser):
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)


def serve(args: argparse.Namespace):
    import uvicorn

    token = os.environ.get("ENCODEASSISTANT_WORKER_TOKEN")
    if args.host not in ("localhost", "127.0.0.1", "::1") and not token:
        raise ValueError("Set ENCODEASSISTANT_WORKER_TOKEN before listening on the network.")
    work = args.work or (args.library / ".encodeassistant-jobs")
    uvicorn.run(create_app(args.library, work, token), host=args.host, port=args.port)


def main():
    parser = argparse.ArgumentParser(description="Run the Encode Assistant worker.")
    add_server_arguments(parser)
    args = parser.parse_args()
    try:
        serve(args)
    except ValueError as error:
        parser.error(str(error))
