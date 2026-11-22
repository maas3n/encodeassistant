# Encode Assistant

Encode Assistant runs a repeatable x264 tuning workflow and asks GPT-6.2 Sol to visually compare matched samples. The graphical client runs on Windows, Linux, macOS, Android, iOS, and Chromebooks with Android app support. It lets you select a source, configure tuning, control jobs, and inspect the final settings and visual comparisons. A separate worker runs on the machine with the video files and encoding tools. Every client connects to that same worker.

## Start the worker

Install Python 3.12+, MediaInfo, AviSynth+, FFMS2, Avs2YUV, standalone x264, and ffprobe. Ensure mediainfo, avs2yuv, x264, and ffprobe are on the worker's PATH. ffprobe reads frame types and timestamps. The worker encodes with the AviSynth+ → Avs2YUV → x264 pipe.

Set OPENAI_API_KEY on the worker. Set ENCODEASSISTANT_FFMS2_PLUGIN to the absolute path of the FFMS2 plugin if it is not autoloaded. For interlaced input, make Yadifmod2 available through autoload or ENCODEASSISTANT_YADIF_PLUGIN. Avs2YUV must be able to load the installed AviSynth+ shared library. ENCODEASSISTANT_MODEL optionally overrides gpt-6.2-sol.

    python -m pip install -r worker/requirements.txt
    python -m worker --library "/path/to/videos"

Open the client and connect to http://127.0.0.1:8765 if it runs on the same machine. On a trusted local network, set ENCODEASSISTANT_WORKER_TOKEN on the worker and use --host 0.0.0.0. Enter the worker's LAN address and the worker token in the app. Use HTTPS if clients need to reach the worker outside that network. The OpenAI API key stays on the worker.

Select a source from the worker library and enter your expected final bitrate plus a slightly lower fixed bitrate for tuning. Leave the crop field blank for automatic side/edge inspection or enter left, top, right, bottom as four even nonnegative pixel amounts. Choose automatic scan inspection, progressive, TFF, or BFF. You can enable a full-source encode after a transparent result or use the returned command separately.

### Workflow

1. Read full-source MediaInfo, sample the video, inspect the scan type, and prepare the AviSynth+ crop. Use Yadifmod2 for a selected interlaced scan mode.
2. At the one lower two-pass bitrate, compare AQ modes 1, 2, and 3 at strength 1.0. Tune strength within the selected mode, test psy-RDO and deblock, and check the combined settings. Both passes use veryslow, with --slow-firstpass on pass 1. Psy-trellis stays at zero.
3. Identify shared interior B-frame presentation timestamps. Send selected matching source/candidate crops to Sol for visual review of hair, shadows, close-up skin, backgrounds, banding and grain. The source video remains on the worker and the API receives comparison images.
4. Check the chosen combination on separate frames at the expected final bitrate. If the check passes, lock its settings and sweep CRF. Surface the highest tested transparent result, exact worker-side commands, sample bitrate, observations, and visual evidence. The job report records inconclusive results too.

The worker uses 8-bit 4:2:0 High@L4.1 settings and retains supported source color tags. It is designed for SDR constant-frame-rate input. Per-frame visual review samples the common B-frames. Final source-wide judgment remains with the user. The optional full encode is video-only. Results, comparison PNGs, logs and any final video are saved under the job folder.

## Build the apps

Run **Build Encode Assistant** in the repository's Actions tab. The build jobs generate platform runners with the pinned Flutter version, build the graphical client, and upload downloadable artifacts.

- Windows, Linux, and macOS have desktop app archives.
- Android and ChromeOS use the same debug APK. The separately labeled ChromeOS artifact includes ARM64 and x86-64 support and can run in a resizable Chromebook window with a mouse and keyboard. Use [ADB on a Chromebook that supports Android apps and sideloading](https://support.google.com/chromebook/answer/9770692) to install the APK.
- iOS includes a simulator app and an unsigned device app. Sign the device build on a Mac before installing it on a physical iPhone.

The build workflow also runs the worker tests and Flutter analysis and widget tests. OpenAI credentials are required on a worker only when running an encoding job. Actions builds the client without media files or an API key.

For local development, install Flutter 3.50.1 and the tools for your target platform. From the repository root, replace linux below with your target.

    flutter create --org com.maas3n --project-name encode_assistant --platforms=linux --no-pub /tmp/encode-assistant-template
    python ci/prepare_platform.py /tmp/encode-assistant-template app linux
    cd app
    flutter pub get
    flutter run -d linux
