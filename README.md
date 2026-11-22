# Encode Assistant

Encode Assistant runs a repeatable x264 tuning workflow and asks GPT-6.2 Sol to visually compare matched samples. The graphical client runs on Windows, Linux, macOS, Android, iOS, and Chromebooks with Android app support. It lets you select a source, configure tuning, control jobs, and inspect the final settings and visual comparisons. A separate worker runs on the machine with the video files and encoding tools. Every client connects to that same worker.

## Download the graphical apps

Get the [bundled GUI release](https://github.com/maas3n/encodeassistant/releases/tag/gui-v0.1.0) for Windows x64, Linux x64, macOS on Apple Silicon or Intel, Android, ChromeOS, and iOS.

The desktop archives include the GUI, worker and CLI, MediaInfo, AviSynth+, Avs2YUV, FFMS2, Yadifmod2, x264, and ffprobe. Extract the archive and follow `START-HERE.md`. On Windows, launch `start-worker.cmd`. On macOS and Linux, run `./start-worker.sh` in Terminal. Choose a writable video folder and enter your OpenAI API key when prompted. Open the graphical app and connect to `http://127.0.0.1:8765`. Linux needs GTK 3. The Windows archive includes the Microsoft Visual C++ Redistributable in its `third-party` folder.

The Android and ChromeOS clients use the same debug-signed APK. The iOS downloads contain an Xcode Simulator app and an unsigned device build. Connect those clients to a desktop or server worker using the [LAN setup below](#serve-the-graphical-clients).

## Terminal CLI

Use `encodeassistant tune` to run the x264 workflow on the machine holding the video. Use `encodeassistant serve` to run a worker that the graphical clients can connect to.

### Run directly from a desktop bundle

Extract the [bundled release](https://github.com/maas3n/encodeassistant/releases/tag/gui-v0.1.0) and open a terminal in the extracted `Encode Assistant` folder. The launcher uses the bundled media tools and plugins. Set `OPENAI_API_KEY` in that terminal for the visual review. The CLI runs locally without starting the graphical app or the worker server.

In Windows Command Prompt:

```bat
encodeassistant.cmd doctor
encodeassistant.cmd tune "D:\Videos\movie.mkv" --expected-kbps 20000 --tuning-kbps 17000 --full-encode
```

In PowerShell, use `./encodeassistant.cmd` in place of `encodeassistant.cmd`. On Linux and macOS:

```sh
./encodeassistant doctor
./encodeassistant tune "/path/to/movie.mkv" --expected-kbps 20000 --tuning-kbps 17000 --full-encode
```

Omit `--full-encode` for a tuning report and recommended settings. Use `--work` to choose where to save the job files.

### Install the CLI separately


#### Homebrew on macOS or Linux

```sh
brew tap maas3n/encodeassistant https://github.com/maas3n/encodeassistant.git
brew install maas3n/encodeassistant/encodeassistant
```

#### Debian 13

```sh
curl -fLO https://github.com/maas3n/encodeassistant/releases/download/cli-v0.1.0/encodeassistant_0.1.0_all.deb
sudo apt install ./encodeassistant_0.1.0_all.deb
```

#### Other Unix systems

Use Python 3.12 or newer and pipx.

```sh
pipx install 'git+https://github.com/maas3n/encodeassistant.git'
```

Standalone archives for macOS and Linux are available on the [CLI release page](https://github.com/maas3n/encodeassistant/releases/tag/cli-v0.1.0).

### Configure the encoding machine

Install MediaInfo, AviSynth+, an AviSynth-enabled FFMS2 plugin, Avs2YUV, standalone x264, and ffprobe. Put `mediainfo`, `avs2yuv`, `x264`, and `ffprobe` on PATH. Homebrew provides `media-info`, `avisynthplus`, `x264`, and `ffmpeg`, which supplies ffprobe. The worker uses ffprobe to read frame timestamps and types. It encodes through AviSynth+ → Avs2YUV → x264.

Set `OPENAI_API_KEY` in the environment where you run the CLI. The default review model is `gpt-6.2-sol`. Set `ENCODEASSISTANT_MODEL` if you want to choose another compatible model. If AviSynth+ needs an explicit path to the FFMS2 plugin, set `ENCODEASSISTANT_FFMS2_PLUGIN`. For interlaced sources, make Yadifmod2 available through AviSynth+ autoload or set `ENCODEASSISTANT_YADIF_PLUGIN` to its path.

```sh
export OPENAI_API_KEY='replace-with-your-openai-api-key'
encodeassistant --version
encodeassistant doctor
```

`doctor` lists the tool paths, tries to read a test frame through AviSynth+ and Avs2YUV with FFMS2 loaded, and checks whether the API key is set. Use `encodeassistant doctor --json` for machine-readable output. For a first tuning run, use a representative SDR, constant-frame-rate source with at least 48 frames.

### Tune a source and get a recommendation

```sh
encodeassistant tune "/srv/videos/My Film.mkv" --expected-kbps 20000 --tuning-kbps 17000
```

Both bitrates are video bitrates in kb/s. In this example, every two-pass tuning candidate uses 17,000 kb/s, slightly below the estimated final rate of 20,000 kb/s. This makes small changes easier to spot. If you omit `--tuning-kbps`, the CLI uses 90% of `--expected-kbps`, rounded down. The expected rate is also used to verify the chosen settings on a second set of excerpts before the CRF sweep. The resulting CRF encode has a source-dependent bitrate.

The CLI checks MediaInfo, prepares the crop and scan handling, compares AQ modes before AQ strength, and tests deblock and psy-RDO. Sol reviews selected frames at timestamps where all candidates encoded a B-frame. After the settings pass the second-set check, the CLI locks them and runs the CRF trials.

### Override a known crop or scan type

```sh
encodeassistant tune "input.mkv" --expected-kbps 20000   --tuning-kbps 17000 --crop 62,0,60,0 --scan progressive
```

Crop values are even, nonnegative pixel counts in **left, top, right, bottom** order. This example removes 62 pixels from the left and 60 from the right. Use `--crop 0,0,0,0` to keep the whole frame or omit `--crop` to detect the borders automatically. `--scan` defaults to `auto`. Use `progressive` for a known progressive source or `tff` and `bff` for interlaced sources with top-field-first and bottom-field-first order, respectively. The interlaced modes use Yadifmod2.

### Save a JSON report or encode the full video

```sh
encodeassistant tune "input.mkv" --expected-kbps 20000 --json > encode-report.json
```

`--json` writes the completed report to stdout. Progress stays on stderr, so it remains visible in the terminal. The JSON includes the absolute `job_directory` path. By default each run saves its files in a separate folder under `.encodeassistant-jobs/` in the current directory. The folder contains `job.json`, `worker.log`, and any comparison PNGs from the visual review. Each panel shows the source on the left and the encoded candidate on the right. When the tests find a transparent CRF, the report includes the selected settings, sample bitrate, and exact commands. The job folder also gets the prepared `movie.avs` script.

```sh
encodeassistant tune "input.mkv" --expected-kbps 20000 --tuning-kbps 17000   --full-encode --work "/srv/encode-jobs"
```

This saves `video.mkv` in the job folder after the CRF check passes. The output contains the encoded video track. If a run finishes without a transparent CRF, it saves the findings and exits with code `3`. Use the saved report and comparison images to see where verification stopped.

| `tune` exit code | Meaning |
| --- | --- |
| `0` | Recommended CRF found and any requested full encode completed. |
| `1` | The running job failed. Open the job folder and inspect `worker.log` and `job.json`. |
| `2` | Command-line input or setup error. Read stderr for details. |
| `3` | Visual review finished without establishing a transparent CRF. |
| `130` | The job was cancelled with Ctrl+C. |

### Serve the graphical clients

Start the worker on the encoding machine for a local GUI connection.

```sh
encodeassistant serve --library "/srv/videos"
```

Connect the app to `http://127.0.0.1:8765`. The server lists source files from `--library` and puts job files in its `.encodeassistant-jobs/` directory by default.

For a GUI on another device, set `ENCODEASSISTANT_WORKER_TOKEN` on the encoding machine and start the worker on your trusted local network.

```sh
export ENCODEASSISTANT_WORKER_TOKEN='replace-with-your-worker-token'
encodeassistant serve --library "/srv/videos" --work "/srv/encode-jobs"   --host 0.0.0.0 --port 8765
```

Enter the server's LAN address, port, and worker token in the app. Run `encodeassistant tune --help`, `encodeassistant doctor --help`, or `encodeassistant serve --help` for the options on your installed version.

## Start the worker from source

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

Run **Package desktop apps with encoding tools** with a successful GUI run ID to assemble the portable desktop archives. The [media input lockfile](ci/media-sources.json) records the versions and SHA-256 hashes. The bundling workflow runs a synthetic encode and verifies FFMS2 decoding and B-frame detection.

The build workflow also runs the worker tests and Flutter analysis and widget tests. OpenAI credentials are required on a worker only when running an encoding job. Actions builds the client without media files or an API key.

For local development, install Flutter 3.50.1 and the tools for your target platform. From the repository root, replace linux below with your target.

    flutter create --org com.maas3n --project-name encode_assistant --platforms=linux --no-pub /tmp/encode-assistant-template
    python ci/prepare_platform.py /tmp/encode-assistant-template app linux
    cd app
    flutter pub get
    flutter run -d linux


## Support encodeassistant

If encodeassistant is useful to you and you'd like to support its development, Bitcoin donations are appreciated but entirely optional.

<img src="https://upload.wikimedia.org/wikipedia/commons/4/46/Bitcoin.svg" width="14" height="14"> **BTC:** `bc1q79hj2zukfmm75278a7wssjmexanuhvs5nequel`


## License

encodeassistant is licensed under the [MIT License](LICENSE). Third-party components remain governed by their own licenses.
