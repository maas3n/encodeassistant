"""Assemble a relocatable GUI, worker, and media toolkit and smoke-test it."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
SH_LAUNCHER = """#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PATH="$base/tools/bin:$PATH"
export {loader_path}="$base/tools/lib${{{loader_path}:+:${loader_path}}}"
export ENCODEASSISTANT_FFMS2_PLUGIN="$base/tools/lib/ffms2{suffix}"
if [ -f "$base/tools/lib/yadifmod2{suffix}" ]; then
    export ENCODEASSISTANT_YADIF_PLUGIN="$base/tools/lib/yadifmod2{suffix}"
fi
exec "$base/runtime/encodeassistant" "$@"
"""
SH_WORKER = """#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -eq 0 ]; then
    printf 'Path to your video folder: '
    IFS= read -r library
    set -- --library "$library"
fi
exec "$base/encodeassistant" serve --prompt-key "$@"
"""
CMD_LAUNCHER = r"""@echo off
setlocal
set "PATH=%~dp0tools\bin;%PATH%"
set "ENCODEASSISTANT_FFMS2_PLUGIN=%~dp0tools\bin\ffms2.dll"
set "ENCODEASSISTANT_YADIF_PLUGIN=%~dp0tools\bin\yadifmod2.dll"
"%~dp0runtime\encodeassistant.exe" %*
"""
CMD_WORKER = r"""@echo off
setlocal
set "library=%~1"
if not defined library set /p "library=Path to your video folder: "
if not defined library exit /b 1
call "%~dp0encodeassistant.cmd" serve --prompt-key --library "%library%"
if errorlevel 1 pause
"""


def extract_app(archive, app, family):
    app.mkdir()
    if family == "macos":
        subprocess.run(["ditto", "-x", "-k", archive, app], check=True)
        return app / "encode_assistant.app/Contents/MacOS/encode_assistant"
    if family == "linux":
        subprocess.run(["tar", "-xf", archive, "-C", app, "--strip-components=1"], check=True)
        return app / "encode_assistant"
    with ZipFile(archive) as files:
        files.extractall(app)
    return app / "encode_assistant.exe"


def package_tools(prefix, bundle, family):
    tools = bundle / "tools"
    shutil.copytree(prefix / "notices", tools / "notices")
    shutil.copy2(HERE / "media-sources.json", tools / "notices")
    shutil.copytree(prefix / "bin", tools / "bin", ignore=shutil.ignore_patterns("*.a"))
    lib = tools / "lib"
    lib.mkdir()
    for source in (prefix / "lib").iterdir():
        if source.is_file() and (".so" in source.name or source.suffix == ".dylib"):
            shutil.copy2(source, lib / source.name, follow_symlinks=False)
    if family == "windows":
        (bundle / "encodeassistant.cmd").write_text(CMD_LAUNCHER, newline="\r\n")
        (bundle / "start-worker.cmd").write_text(CMD_WORKER, newline="\r\n")
        return
    loader_path = "DYLD_LIBRARY_PATH" if family == "macos" else "LD_LIBRARY_PATH"
    suffix = ".dylib" if family == "macos" else ".so"
    launcher = SH_LAUNCHER.format(loader_path=loader_path, suffix=suffix)
    for name, content in (("encodeassistant", launcher), ("start-worker.sh", SH_WORKER)):
        script = bundle / name
        script.write_text(content)
        script.chmod(0o755)


def smoke_test(bundle, family):
    windows = family == "windows"
    suffix = ".exe" if windows else ""
    tools = bundle / "tools/bin"
    libraries = bundle / "tools/lib"
    ffms = tools / "ffms2.dll" if windows else libraries / ("ffms2.dylib" if family == "macos" else "ffms2.so")
    yadif = ffms.with_name(ffms.name.replace("ffms2", "yadifmod2"))
    env = {
        **os.environ,
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "ENCODEASSISTANT_FFMS2_PLUGIN": str(ffms),
        "OPENAI_API_KEY": "unused-during-smoke-test",
    }
    if not windows:
        env["DYLD_LIBRARY_PATH" if family == "macos" else "LD_LIBRARY_PATH"] = str(libraries)
    # Invoke the actual Unix launcher so tooling and library lookup are checked as shipped.
    cli = bundle / ("runtime/encodeassistant.exe" if windows else "encodeassistant")
    doctor = subprocess.run([cli, "doctor", "--json"], env=env, stdout=subprocess.PIPE, text=True)
    print(doctor.stdout, flush=True)
    doctor.check_returncode()
    checks = json.loads(doctor.stdout)
    assert checks["ready"] and all(Path(p).parent == tools for p in checks["tools"].values())
    with tempfile.TemporaryDirectory(prefix="encode-assistant-smoke-") as directory:
        work = Path(directory)
        script = work / "source.avs"
        script.write_text('BlankClip(length=72, width=64, height=64, fps=24, pixel_type="YV12")\n')
        movie = work / "video.mkv"
        with subprocess.Popen([tools / f"avs2yuv{suffix}", script, "-o", "-"], stdout=subprocess.PIPE, env=env) as avs:
            subprocess.run([
                tools / f"x264{suffix}", "--demuxer", "y4m", "--preset", "veryslow",
                "--profile", "high", "--level", "4.1", "--no-dct-decimate", "--no-mbtree",
                "--no-fast-pskip", "--output-csp", "i420", "--output-depth", "8",
                "--crf", "17", "--output", movie, "-",
            ], stdin=avs.stdout, env=env, check=True, timeout=90)
            assert avs.wait(timeout=15) == 0
        subprocess.run([tools / f"mediainfo{suffix}", movie], env=env, check=True)
        probe = subprocess.check_output([
            tools / f"ffprobe{suffix}", "-v", "error", "-show_frames",
            "-show_entries", "frame=pict_type", "-of", "json", movie,
        ], env=env)
        frames = json.loads(probe)["frames"]
        assert len(frames) == 72 and any(frame["pict_type"] == "B" for frame in frames)
        path = movie.as_posix()
        script.write_text(f'LoadPlugin("{ffms.as_posix()}")\nFFVideoSource("{path}").Trim(0, -1)\n')
        raw = subprocess.check_output([tools / f"avs2yuv{suffix}", script, "-o", "-"], env=env)
        assert raw.startswith(b"YUV4MPEG2 W64 H64")
        if yadif.exists():
            script.write_text(
                f'LoadPlugin("{yadif.as_posix()}")\n'
                'BlankClip(length=4, width=64, height=64, pixel_type="YV12")\n'
                'AssumeTFF().Yadifmod2(order=1).Trim(0, -1)\n'
            )
            raw = subprocess.check_output([tools / f"avs2yuv{suffix}", script, "-o", "-"], env=env)
            assert raw.startswith(b"YUV4MPEG2 W64 H64")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform")
    parser.add_argument("gui_archive", type=Path)
    parser.add_argument("worker", type=Path)
    parser.add_argument("media", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    family = args.platform.split("-")[0]
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve() / f"encode-assistant-{args.platform}"
    with tempfile.TemporaryDirectory(prefix="encode-bundle-") as directory:
        bundle = Path(directory) / "Encode Assistant"
        bundle.mkdir()
        gui = extract_app(args.gui_archive.resolve(), bundle / "app", family)
        assert gui.is_file(), f"Missing GUI executable: {gui}"
        if family == "macos":
            architecture = args.platform.removeprefix("macos-")
            supported = subprocess.check_output(["lipo", "-archs", gui], text=True).split()
            assert architecture in supported, f"GUI architectures: {supported}"
        runtime = bundle / "runtime"
        runtime.mkdir()
        shutil.copy2(args.worker, runtime / args.worker.name)
        shutil.copy2(HERE / "Desktop-Setup.md", bundle / "START-HERE.md")
        shutil.copy2(HERE.parent / "LICENSE", bundle)
        package_tools(args.media, bundle, family)
        smoke_test(bundle, family)
        if family == "macos":
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", bundle, f"{output}.zip"], check=True)
        else:
            shutil.make_archive(str(output), "zip" if family == "windows" else "gztar", directory, bundle.name)


if __name__ == "__main__":
    main()
