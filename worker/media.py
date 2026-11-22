from __future__ import annotations

import base64
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from pathlib import Path
from typing import BinaryIO

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Settings:
    deblock: str = "0:0"
    psy: float = 1.0
    mode: int = 2
    strength: float = 1.0

    def flags(self) -> list[str]:
        return [
            "--deblock", self.deblock, "--psy-rd", f"{self.psy:.2f}:0.00",
            "--aq-mode", str(self.mode), "--aq-strength", str(self.strength),
        ]


FIXED = [
    "--demuxer", "y4m", "--preset", "veryslow", "--threads", "4",
    "--output-csp", "i420", "--output-depth", "8", "--profile", "high",
    "--level", "4.1", "--no-dct-decimate", "--no-mbtree", "--no-fast-pskip",
]
REGION_COUNT = 10
FRAMES_PER_REGION = 24


class Cancelled(Exception):
    pass


class Runner:
    def __init__(self, directory: Path, cancelled: threading.Event):
        self.directory = directory
        self.cancelled = cancelled

    def run(self, commands: list[list[str]], output: BinaryIO | int = subprocess.DEVNULL):
        processes = []
        with (self.directory / "worker.log").open("ab") as log:
            try:
                for index, command in enumerate(commands):
                    self.check()
                    previous = processes[-1].stdout if processes else None
                    process = subprocess.Popen(
                        command, cwd=self.directory, stdin=previous,
                        stdout=output if index == len(commands) - 1 else subprocess.PIPE,
                        stderr=log,
                    )
                    processes.append(process)
                    if previous:
                        previous.close()
                while any(p.poll() is None for p in processes):
                    if self.cancelled.wait(0.15):
                        raise Cancelled()
                for command, process in zip(commands, processes):
                    if process.returncode:
                        log.flush()
                        tail = (self.directory / "worker.log").read_bytes()[-1800:].decode(
                            "utf-8", errors="replace"
                        )
                        raise RuntimeError(f"{command[0]} exited with {process.returncode}.\n{tail}")
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    if process.stdout:
                        process.stdout.close()

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def json(self, command: list[str]) -> dict:
        import tempfile
        with tempfile.TemporaryFile() as result:
            self.run([command], result)
            result.seek(0)
            return json.load(result)

    def avs(self, name: str, lines: list[str]) -> Path:
        path = self.directory / f"{name}.avs"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def y4m(self, script: Path) -> Path:
        path = script.with_suffix(".y4m")
        with path.open("wb") as output:
            self.run([["avs2yuv", str(script), "-o", "-"]], output)
        return path


def quote_avs(path: Path) -> str:
    value = path.as_posix()
    if any(c in value for c in ('"', "\n", "\r", "\x00")):
        raise ValueError("AviSynth paths must not contain quotation marks or line breaks.")
    return f'"{value}"'


def source_lines(source: Path, runner: Runner) -> list[str]:
    plugin = os.environ.get("ENCODEASSISTANT_FFMS2_PLUGIN")
    lines = [f"LoadPlugin({quote_avs(Path(plugin).resolve())})"] if plugin else []
    cache = runner.directory / (source.stem + ".ffindex")
    lines.append(
        f"FFVideoSource({quote_avs(source)}, threads=2, cachefile={quote_avs(cache)})"
    )
    return lines


def inspect_source(runner: Runner, source: Path) -> tuple[dict, Fraction, int]:
    for tool in ("mediainfo", "avs2yuv", "x264", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is required on the worker PATH.")
    info = runner.json(["mediainfo", "--Output=JSON", str(source)])
    tracks = info.get("media", {}).get("track", [])
    video = next((track for track in tracks if track.get("@type") == "Video"), None)
    if not video:
        raise ValueError("MediaInfo found no video track.")
    probe = runner.json([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,nb_frames,duration:format=duration",
        "-of", "json", str(source),
    ])
    stream = probe["streams"][0]
    rate = Fraction(stream.get("avg_frame_rate", "0"))
    if not rate:
        raise ValueError("The source has no usable average frame rate.")
    raw_frames = stream.get("nb_frames") or video.get("FrameCount")
    duration = stream.get("duration") or probe.get("format", {}).get("duration")
    try:
        length = int(raw_frames)
    except (TypeError, ValueError):
        length = int(Fraction(duration or "0") * rate)
    if duration and duration != "N/A":
        estimate = int(Fraction(duration) * rate)
        if estimate > 0 and length > estimate * 1.1:
            length = estimate
    if length < FRAMES_PER_REGION * 2:
        raise ValueError("The source must contain at least 48 frames for separate tuning and verification.")
    return video, rate, length


def sample_ranges(length: int, verify: bool) -> list[tuple[int, int]]:
    frames = FRAMES_PER_REGION
    sections = min(REGION_COUNT, length // (frames * 2))
    ranges = []
    for i in range(sections):
        low = i * length // sections
        high = (i + 1) * length // sections
        reserve = high - low - frames * 2
        start = low + reserve // 2 + (frames if verify else 0)
        ranges.append((start, start + frames - 1))
    return ranges


def sample_lines(base: list[str], ranges: list[tuple[int, int]]) -> list[str]:
    return base + ["c = last", " ++ ".join(f"c.Trim({a}, {b})" for a, b in ranges)]


def frames_from_y4m(path: Path, selected: set[int] | None = None):
    with path.open("rb") as stream:
        header = stream.readline().decode("ascii").split()
        if not header or header[0] != "YUV4MPEG2":
            raise ValueError(f"{path.name} has no Y4M header.")
        data = {part[0]: part[1:] for part in header[1:]}
        if not data.get("C", "420").startswith("420") or "p10" in data.get("C", ""):
            raise ValueError("Expected 8-bit 4:2:0 frames from AviSynth+.")
        width, height = int(data["W"]), int(data["H"])
        size = width * height * 3 // 2
        index = 0
        while marker := stream.readline():
            if not marker.startswith(b"FRAME"):
                raise ValueError("Invalid Y4M frame boundary.")
            if selected is None or index in selected:
                raw = stream.read(size)
                if len(raw) != size:
                    raise ValueError("AviSynth+ returned a truncated frame.")
                yield index, width, height, raw
            else:
                stream.seek(size, os.SEEK_CUR)
            index += 1


def detect_crop(path: Path, count: int, black_floor: int) -> list[int]:
    selected = {i for i in range(4, count, 6)}
    extents = []
    dims = None
    for _, w, h, raw in frames_from_y4m(path, selected):
        dims = (w, h)
        y = np.frombuffer(raw, dtype=np.uint8, count=w * h).reshape(h, w)
        lit = y > black_floor
        cols = np.flatnonzero(lit.sum(axis=0) >= max(8, h // 60))
        rows = np.flatnonzero(lit.sum(axis=1) >= max(8, w // 60))
        if len(cols) > w // 3 and len(rows) > h // 3:
            extents.append([cols[0], rows[0], w - 1 - cols[-1], h - 1 - rows[-1]])
    if not extents or not dims:
        return [0, 0, 0, 0]
    extents = np.asarray(extents)
    baseline = np.quantile(extents, 0.15, axis=0, method="lower")
    limits = (dims[0] // 6, dims[1] // 6, dims[0] // 6, dims[1] // 6)
    return [
        int(boundary + boundary % 2)
        if 2 <= boundary <= limit and np.mean(abs(extents[:, i] - boundary) <= 2) >= 0.7
        else 0
        for i, (boundary, limit) in enumerate(zip(baseline, limits))
    ]


def frame_types(runner: Runner, path: Path, rate: Fraction, count: int) -> set[int]:
    result = runner.json([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time,pict_type", "-of", "json", str(path),
    ])
    frames = result.get("frames", [])
    if len(frames) != count:
        raise ValueError(f"{path.name} has {len(frames)} frames, expected {count}.")
    shared = set()
    for index, frame in enumerate(frames):
        pts = Fraction(frame["best_effort_timestamp_time"])
        if abs(pts - index / rate) > Fraction(1, 1000):
            raise ValueError(f"{path.name} has an unexpected timestamp at frame {index}.")
        if frame["pict_type"] == "B" and 4 <= index % FRAMES_PER_REGION < FRAMES_PER_REGION - 4:
            shared.add(index)
    return shared


def png_url(image: Image.Image) -> str:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def color_tags(video: dict) -> list[str]:
    tags = {
        "BT.709": "bt709", "BT.2020": "bt2020", "BT.2020 non-constant": "bt2020nc",
        "BT.601": "smpte170m", "SMPTE 170M": "smpte170m", "BT.470 System B/G": "bt470bg",
        "SMPTE 2084": "smpte2084", "HLG": "arib-std-b67",
    }
    args = []
    if range_name := {"Limited": "tv", "Full": "pc"}.get(video.get("colour_range")):
        args.extend(["--range", range_name])
    for prop, flag in (
        ("colour_primaries", "--colorprim"),
        ("transfer_characteristics", "--transfer"),
        ("matrix_coefficients", "--colormatrix"),
    ):
        value = tags.get(video.get(prop))
        if value:
            args.extend([flag, value])
    try:
        sar = Fraction(str(video.get("PixelAspectRatio", "1")).replace(":", "/")).limit_denominator(255)
        if sar > 0:
            args.extend(["--sar", f"{sar.numerator}:{sar.denominator}"])
    except (ValueError, ZeroDivisionError):
        pass
    return args


def render_frame(w: int, h: int, raw: bytes, video: dict) -> Image.Image:
    rows = np.frombuffer(raw, dtype=np.uint8)
    y_size = w * h
    u_size = y_size // 4
    y = rows[:y_size].reshape(h, w).astype(np.float32)
    u = rows[y_size:y_size + u_size].reshape(h // 2, w // 2).astype(np.float32)
    v = rows[y_size + u_size:].reshape(h // 2, w // 2).astype(np.float32)
    if video.get("colour_range") == "Full":
        y /= 255
        u = (u - 128) / 255
        v = (v - 128) / 255
    else:
        y = (y - 16) / 219
        u = (u - 128) / 224
        v = (v - 128) / 224
    u, v = (c.repeat(2, axis=0).repeat(2, axis=1) for c in (u, v))
    kr, kb = {
        "BT.601": (0.299, 0.114), "SMPTE 170M": (0.299, 0.114),
        "BT.2020 non-constant": (0.2627, 0.0593),
    }.get(video.get("matrix_coefficients"), (0.2126, 0.0722))
    kg = 1 - kr - kb
    channels = (y + 2 * (1 - kr) * v,
                y - 2 * kb * (1 - kb) / kg * u - 2 * kr * (1 - kr) / kg * v,
                y + 2 * (1 - kb) * u)
    return Image.fromarray((np.clip(np.stack(channels, axis=-1), 0, 1) * 255 + 0.5).astype("uint8"))


def regions(image: Image.Image) -> list[tuple[int, int, int, int]]:
    g = np.asarray(image.convert("L"), dtype=np.float32)
    h, w = g.shape
    pw, ph = min(w, 384), min(h, 256)
    choices = []
    for x, y in product(np.linspace(0, w - pw, 4, dtype=int), np.linspace(0, h - ph, 3, dtype=int)):
        block = g[y:y + ph, x:x + pw]
        local_detail = float(abs(np.diff(block, axis=1)).mean()) if pw > 1 else 0
        choices.append((local_detail, float(block.mean()), (int(x), int(y), int(x + pw), int(y + ph))))
    texture = max(choices)[2]
    shadows = min(choices, key=lambda x: abs(30 - x[1]) - 0.35 * x[0])[2]
    center = ((w - pw) // 2, (h - ph) // 2, (w + pw) // 2, (h + ph) // 2)
    return list(dict.fromkeys([texture, shadows, center]))


def make_comparison(reference: Image.Image, candidate: Image.Image) -> Image.Image:
    if reference.size != candidate.size:
        raise ValueError("Candidate and source dimensions differ.")
    w, h = reference.size
    thumbs = [im.copy() for im in (reference, candidate)]
    for thumbnail in thumbs:
        thumbnail.thumbnail((384, 238))
    rw, rh = thumbs[0].size
    rois = regions(reference)
    panel = Image.new("RGB", (2 * max(rw, min(w, 384)), rh + 8 + len(rois) * (min(h, 256) + 6)), "#202326")
    for column, (image, thumbnail) in enumerate(zip((reference, candidate), thumbs)):
        x = column * panel.width // 2
        panel.paste(thumbnail, (x, 0))
        row = rh + 8
        for roi in rois:
            panel.paste(image.crop(roi), (x, row))
            row += min(h, 256) + 6
    return panel


def command_text(script: str, args: list[str], output: str) -> dict[str, str]:
    a = ["avs2yuv", script, "-o", "-"]
    b = ["x264", *args, "--output", output, "-"]
    return {
        "bash": f"{shlex.join(a)} | {shlex.join(b)}",
        "windows_cmd": f"{subprocess.list2cmdline(a)} | {subprocess.list2cmdline(b)}",
    }


SAFE_JOB_NAME = re.compile(r"^[a-f0-9]{12}$")
