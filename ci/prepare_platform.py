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


def configure_android(path: Path):
    ET.register_namespace("android", ANDROID)
    tree = ET.parse(path, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    manifest = tree.getroot()
    name = f"{{{ANDROID}}}name"
    application = manifest.find("application")
    if application is None:
        raise ValueError("The generated Android manifest has no application.")

    if not any(element.get(name) == "android.permission.INTERNET"
               for element in manifest.findall("uses-permission")):
        manifest.insert(0, ET.Element("uses-permission", {name: "android.permission.INTERNET"}))
    touchscreen = next((element for element in manifest.findall("uses-feature")
                        if element.get(name) == "android.hardware.touchscreen"), None)
    if touchscreen is None:
        touchscreen = ET.Element("uses-feature", {name: "android.hardware.touchscreen"})
        manifest.insert(0, touchscreen)
    touchscreen.set(f"{{{ANDROID}}}required", "false")
    application.set(f"{{{ANDROID}}}resizeableActivity", "true")
    application.set(f"{{{ANDROID}}}usesCleartextTraffic", "true")
    ET.indent(tree, space="    ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def prepare(template: Path, app: Path, platform: str):
    target = app / platform
    shutil.copytree(template / platform, target, dirs_exist_ok=True)
    if platform == "android":
        configure_android(target / "app/src/main/AndroidManifest.xml")
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
