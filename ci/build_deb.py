"""Build an architecture-independent Debian package for the CLI."""
from __future__ import annotations

import argparse
import runpy
import shutil
import subprocess
import tempfile
from pathlib import Path


def build(destination: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    version = runpy.run_path(str(root / "worker/__init__.py"))["__version__"]
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    package = destination / f"encodeassistant_{version}_all.deb"
    with tempfile.TemporaryDirectory(prefix="encodeassistant-deb-") as temp:
        stage = Path(temp)
        library = stage / "usr/lib/encodeassistant/worker"
        library.mkdir(parents=True)
        for file in (root / "worker").glob("*.py"):
            shutil.copyfile(file, library / file.name)

        commands = stage / "usr/bin"
        commands.mkdir(parents=True)
        command = commands / "encodeassistant"
        command.write_text(
            '#!/bin/sh\n'
            'PYTHONPATH=/usr/lib/encodeassistant exec /usr/bin/python3 -m worker.cli "$@"\n',
            encoding="utf-8",
        )
        command.chmod(0o755)
        docs = stage / "usr/share/doc/encodeassistant"
        docs.mkdir(parents=True)
        shutil.copyfile(root / "LICENSE", docs / "copyright")
        shutil.copyfile(root / "README.md", docs / "README.md")

        metadata = stage / "DEBIAN"
        metadata.mkdir()
        (metadata / "control").write_text(
            f"Package: encodeassistant\nVersion: {version}\n"
            "Architecture: all\nSection: video\nPriority: optional\n"
            "Maintainer: Encode Assistant <maas3n@users.noreply.github.com>\n"
            "Depends: python3 (>= 3.12), python3-pydantic (>= 2), python3-fastapi, "
            "python3-uvicorn, python3-httpx, python3-numpy, python3-pil\n"
            "Recommends: mediainfo, ffmpeg, x264\n"
            "Homepage: https://github.com/maas3n/encodeassistant\n"
            "Description: headless x264 encoding assistant\n"
            " Runs the AviSynth+ to x264 tuning workflow and reviews matched B-frames.\n"
            " Can also serve graphical Encode Assistant clients.\n",
            encoding="utf-8",
        )
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(package)], check=True)
    return package


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(build(parser.parse_args().destination))
