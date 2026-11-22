from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

from . import __version__
from .media import Cancelled, Runner, frames_from_y4m, quote_avs
from .server import Job, JobRequest, add_server_arguments, serve
from .workflow import Workflow


class TerminalJob(Job):
    def __init__(self, directory: Path, request: JobRequest):
        super().__init__(directory, request)
        self.last_message = None

    def update(self, **fields):
        super().update(**fields)
        message = self.state["message"]
        if message != self.last_message:
            self.last_message = message
            print(f"{self.state['progress']:>4.0%}  {message}", file=sys.stderr, flush=True)


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("enter a whole number in kb/s") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("enter a positive number")
    return number


def crop_values(value: str) -> list[int]:
    try:
        crop = [int(part) for part in value.split(",")]
    except ValueError:
        crop = []
    if len(crop) != 4 or any(n < 0 or n % 2 for n in crop):
        raise argparse.ArgumentTypeError("use four nonnegative even pixel counts: left,top,right,bottom")
    return crop


def doctor() -> dict:
    tools = {name: shutil.which(name) for name in ("mediainfo", "avs2yuv", "x264", "ffprobe")}
    result = {
        "tools": tools,
        "openai_key_configured": bool(os.environ.get("OPENAI_API_KEY")),
        "avisynth_ffms2": "Avs2YUV is missing from PATH",
        "ready": False,
    }
    if tools["avs2yuv"]:
        try:
            with tempfile.TemporaryDirectory(prefix="encodeassistant-doctor-") as tmp:
                runner = Runner(Path(tmp), threading.Event())
                plugin = os.environ.get("ENCODEASSISTANT_FFMS2_PLUGIN")
                lines = [f"LoadPlugin({quote_avs(Path(plugin).expanduser().resolve())})"] if plugin else []
                lines += [
                    'Assert(FunctionExists("FFVideoSource"), "FFMS2 is not loaded; configure ENCODEASSISTANT_FFMS2_PLUGIN")',
                    'BlankClip(length=1, width=16, height=16, pixel_type="YV12")',
                ]
                script = runner.avs("doctor", lines)
                frames = list(frames_from_y4m(runner.y4m(script)))
                if len(frames) != 1 or frames[0][1:3] != (16, 16):
                    raise RuntimeError("Avs2YUV did not return the expected test frame.")
            result["avisynth_ffms2"] = "ok"
        except (OSError, ValueError, RuntimeError) as error:
            result["avisynth_ffms2"] = str(error)
    result["ready"] = (
        all(tools.values()) and result["openai_key_configured"] and result["avisynth_ffms2"] == "ok"
    )
    return result


def show_doctor(args: argparse.Namespace) -> int:
    result = doctor()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for tool, path in result["tools"].items():
            print(f"{tool:10}  {path or 'missing from PATH'}")
        print(f"AviSynth+   {result['avisynth_ffms2']}")
        print(f"OpenAI key  {'configured' if result['openai_key_configured'] else 'set OPENAI_API_KEY'}")
    return 0 if result["ready"] else 1


def tune(args: argparse.Namespace) -> int:
    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Source video does not exist: {source}")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY before starting live visual tuning.")
    tuning_kbps = args.tuning_kbps
    if tuning_kbps is None:
        tuning_kbps = args.expected_kbps * 9 // 10
    request = JobRequest(
        source=source.name, tuning_kbps=tuning_kbps, expected_kbps=args.expected_kbps,
        crop=args.crop, scan=args.scan, full_encode=args.full_encode,
    )
    directory = args.work.expanduser().resolve() / uuid4().hex[:12]
    directory.mkdir(parents=True)
    job = TerminalJob(directory, request)
    job.update(
        status="running",
        message=f"Tuning at {tuning_kbps:,} kb/s with an expected final rate of {args.expected_kbps:,} kb/s",
    )
    try:
        report = Workflow(job, source).run()
    except (Cancelled, KeyboardInterrupt):
        job.cancelled.set()
        job.update(status="cancelled", stage="cancelled", message="The job was cancelled.")
        print(f"Job folder: {directory}", file=sys.stderr)
        return 130
    except Exception as error:
        message = str(error).replace(os.environ["OPENAI_API_KEY"], "[redacted]")
        job.update(status="failed", stage="failed", message=message)
        print(f"Job folder: {directory}", file=sys.stderr)
        return 1

    state = {
        "status": "completed", "stage": "completed", "progress": 1,
        "message": report.get("message", "Encoding recommendation ready"), "report": report,
    }
    job.update(**state)
    if args.json:
        print(json.dumps({"job_directory": str(directory), **job.snapshot()}, indent=2))
    else:
        if "crf" in report:
            settings = report["settings"]
            print(f"CRF {report['crf']:g} · {report['sample_kbps']:g} kb/s on verification excerpts")
            print(f"Deblock {settings['deblock']} · Psy-RDO {settings['psy']} · AQ {settings['mode']} / {settings['strength']}")
            print(report["command"]["windows_cmd" if os.name == "nt" else "bash"])
        else:
            print(state["message"])
        if file := report.get("output_file"):
            print(f"Video: {directory / file}")
        print(f"Report: {directory / 'job.json'}")
    return 0 if "crf" in report else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="encodeassistant", description="Run and visually compare x264 tuning encodes.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    tune_parser = commands.add_parser("tune", help="Run two-pass tuning and a matched B-frame CRF sweep")
    tune_parser.add_argument("source", type=Path, help="Source video file")
    tune_parser.add_argument("--expected-kbps", required=True, type=positive_int, help="Expected final video bitrate")
    tune_parser.add_argument("--tuning-kbps", type=positive_int, help="Fixed two-pass bitrate (default: 90%% of expected)")
    tune_parser.add_argument("--crop", type=crop_values, help="Even pixel crop as left,top,right,bottom (default: auto)")
    tune_parser.add_argument("--scan", choices=("auto", "progressive", "tff", "bff"), default="auto")
    tune_parser.add_argument("--work", type=Path, default=Path(".encodeassistant-jobs"), help="Folder for reports and outputs")
    tune_parser.add_argument("--full-encode", action="store_true", help="Encode the full source after a transparent CRF result")
    tune_parser.add_argument("--json", action="store_true", help="Write the completed report as JSON on stdout")
    tune_parser.set_defaults(action=tune)
    doctor_parser = commands.add_parser("doctor", help="Check the local tools, FFMS2 and API key configuration")
    doctor_parser.add_argument("--json", action="store_true", help="Write the checks as JSON")
    doctor_parser.set_defaults(action=show_doctor)
    server_parser = commands.add_parser("serve", help="Start the worker for the graphical clients")
    add_server_arguments(server_parser)
    server_parser.set_defaults(action=serve)
    args = parser.parse_args(argv)
    try:
        return args.action(args) or 0
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
