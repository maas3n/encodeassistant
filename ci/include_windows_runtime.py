"""Add Microsoft's pinned x64 Visual C++ Redistributable to a Windows bundle."""
import argparse
import hashlib
import tempfile
from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZIP_DEFLATED, ZipFile

SHA256 = "9c02c9ed120f671b900e6b9471d890e3b2414117a7e53f4ae2e855466fa2b7c9"
URL = (
    "https://download.visualstudio.microsoft.com/download/pr/"
    f"78d061c5-9ef3-42ab-98ed-3309d1095dc4/{SHA256.upper()}/VC_redist.x64.exe"
)
REDIST = "Encode Assistant/third-party/VC_redist.x64.exe"
INSTRUCTIONS = """# Microsoft Visual C++ Runtime

The Windows GUI uses Microsoft's Visual C++ Runtime. If Windows reports a
missing MSVCP140.dll or VCRUNTIME140.dll, run the included Microsoft installer
(`VC_redist.x64.exe`), then reopen the app.

[Microsoft's Redistributable documentation](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/)
"""


def include(archive, installer):
    with installer.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SHA256:
            raise ValueError("Microsoft Redistributable checksum mismatch")
    with ZipFile(archive, "a", compression=ZIP_DEFLATED) as bundle:
        if REDIST in bundle.namelist():
            assert hashlib.sha256(bundle.read(REDIST)).hexdigest() == SHA256
            return
        bundle.write(installer, REDIST)
        bundle.writestr("Encode Assistant/third-party/MICROSOFT-RUNTIME.md", INSTRUCTIONS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--installer", type=Path)
    args = parser.parse_args()
    if args.installer:
        include(args.archive, args.installer)
    else:
        with tempfile.TemporaryDirectory() as directory:
            installer = Path(directory) / "VC_redist.x64.exe"
            urlretrieve(URL, installer)
            include(args.archive, installer)


if __name__ == "__main__":
    main()
