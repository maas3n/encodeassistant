"""Copy the Flutter platform template and configure worker network access."""
from __future__ import annotations

import argparse
import plistlib
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET


ANDROID = "http://schemas.android.com/apk/res/android"


def plist_update(path: Path, fields: dict):
    with path.open("rb") as handle:
        data = plistlib.load(handle)
    data.update(fields)
    with path.open("wb") as handle:
        plistlib.dump(data, handle, sort_keys=False)


def prepare(template: Path, app: Path, platform: str):
    target = app / platform
    shutil.copytree(template / platform, target, dirs_exist_ok=True)
    if platform == "android":
        ET.register_namespace("android", ANDROID)
        manifest = target / "app/src/main/AndroidManifest.xml"
        # Keep literal text and comments from the generated Gradle template.
        content = manifest.read_text(encoding="utf-8")
        permission = '    <uses-permission android:name="android.permission.INTERNET" />'
        if permission not in content:
            content = content.replace("    <application", permission + "\n    <application", 1)
        if 'android:usesCleartextTraffic=' not in content:
            content = content.replace("    <application", '    <application android:usesCleartextTraffic="true"', 1)
        ET.fromstring(content)
        manifest.write_text(content, encoding="utf-8")
    if platform == "ios":
        plist_update(target / "Runner/Info.plist", {
            "NSLocalNetworkUsageDescription": "Connect to your Encode Assistant worker.",
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        })
    if platform == "macos":
        for settings in ("DebugProfile.entitlements", "Release.entitlements"):
            plist_update(target / "Runner" / settings, {"com.apple.security.network.client": True})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("template", type=Path)
    parser.add_argument("app", type=Path)
    parser.add_argument("platform", choices=("android", "ios", "linux", "macos", "windows"))
    args = parser.parse_args()
    prepare(args.template, args.app, args.platform)


if __name__ == "__main__":
    main()
