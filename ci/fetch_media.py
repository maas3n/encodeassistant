"""Download and verify the sources for the desktop media tools."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from urllib.request import Request, urlopen

LOCK = Path(__file__).with_name("media-sources.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--vendor", choices=["win", "mac"])
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)

    for name, source in json.loads(LOCK.read_text()).items():
        if name.startswith("mediainfo-") and name != f"mediainfo-{args.vendor}":
            continue
        path = args.directory / source["archive"]
        if not path.exists():
            request = Request(source["url"], headers={"User-Agent": "Encode Assistant release build"})
            with urlopen(request, timeout=120) as response, path.open("wb") as target:
                shutil.copyfileobj(response, target)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != source["sha256"]:
            raise ValueError(f"Checksum mismatch for {path}")
        print(f"Verified {path}", flush=True)


if __name__ == "__main__":
    main()
