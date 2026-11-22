# Encode Assistant desktop bundle

Extract the entire archive and keep its folder structure. You can run the bundled CLI directly or connect the graphical app to the worker.

## Use the graphical app

Launch the worker, then open the graphical app. The worker asks for your OpenAI API key in its terminal if the key is absent from the environment.

| Platform | Start the worker | Open the app |
| --- | --- | --- |
| Windows | Double-click `start-worker.cmd` and enter the path to your video folder. | Run `app\encode_assistant.exe`. |
| Linux | Run `./start-worker.sh` and enter the path to your video folder. | Run `./app/encode_assistant`. GTK 3 is required. |
| macOS | Run `./start-worker.sh` in Terminal and enter the path to your video folder. | Open `app/encode_assistant.app` in Finder. The app is unsigned for distribution. |

Enter `http://127.0.0.1:8765` as the worker URL in the app. Keep the worker terminal open while encoding. The worker creates `.encodeassistant-jobs/` under the video folder by default. Choose a folder writable by your account.

## Use the bundled CLI

Open a terminal in the extracted `Encode Assistant` folder. The launcher uses the bundled tools, and `tune` runs locally without a worker server. Set `OPENAI_API_KEY` in your terminal for the visual review.

In Windows Command Prompt:

```bat
encodeassistant.cmd doctor
encodeassistant.cmd tune "D:\Videos\movie.mkv" --expected-kbps 20000 --tuning-kbps 17000 --full-encode
```

In PowerShell, invoke the launcher as `./encodeassistant.cmd`. On Linux and macOS:

```sh
./encodeassistant doctor
./encodeassistant tune "/path/to/movie.mkv" --expected-kbps 20000 --tuning-kbps 17000 --full-encode
```

Omit `--full-encode` to get the recommended settings and tuning report. Add `--work` to choose the directory for job files.

## Connect Android, ChromeOS, iOS, or another desktop

Choose a worker token, then start the desktop bundle's worker on your trusted local network. Run these commands from the extracted folder.

```sh
export ENCODEASSISTANT_WORKER_TOKEN='replace-with-your-worker-token'
./start-worker.sh --library "/path/to/videos" --host 0.0.0.0
```

In Windows Command Prompt, use the following commands.

```bat
set "ENCODEASSISTANT_WORKER_TOKEN=replace-with-your-worker-token"
encodeassistant.cmd serve --prompt-key --library "D:\Videos" --host 0.0.0.0
```

In the client, enter the encoding computer's LAN address, for example `http://192.168.1.23:8765`, and your worker token. The API key belongs on the encoding computer. The API receives the selected frame comparisons during a tuning job.

## Included tools

The bundle contains standalone x264, AviSynth+, Avs2YUV, the FFMS2 AviSynth plugin, MediaInfo, and ffprobe with its shared FFmpeg libraries. Yadifmod2 is included for interlaced sources. The Apple Silicon build uses the plugin’s scalar implementation.

Third-party license texts and build inputs are described under `tools/notices`. Source archives and build scripts are also available alongside the desktop downloads on the release page.
