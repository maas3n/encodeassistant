# Encode Assistant desktop bundle

Extract the entire archive and keep its folder structure. Launch the worker, then open the graphical app. The worker asks for your OpenAI API key in its terminal if the key is absent from the environment.

| Platform | Start the worker | Open the app |
| --- | --- | --- |
| Windows | Double-click `start-worker.cmd` and enter the path to your video folder. | Run `app\encode_assistant.exe`. |
| Linux | Run `./start-worker.sh` and enter the path to your video folder. | Run `./app/encode_assistant`. GTK 3 is required. |
| macOS | Run `./start-worker.sh` in Terminal and enter the path to your video folder. | Open `app/encode_assistant.app` in Finder. The app is unsigned for distribution. |

Enter `http://127.0.0.1:8765` as the worker URL in the app. Keep the worker terminal open while encoding. The worker creates `.encodeassistant-jobs/` under the video folder by default. Choose a folder writable by your account.

## Use the bundled CLI

Run `./encodeassistant doctor` on Linux/macOS or `encodeassistant.cmd doctor` in Windows Command Prompt. Set `OPENAI_API_KEY` in that terminal when using the `tune` command directly.

```sh
./encodeassistant tune "/path/to/source.mkv" --expected-kbps 20000 --tuning-kbps 17000
```

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

The bundle contains standalone x264, AviSynth+, Avs2YUV, the FFMS2 AviSynth plugin, MediaInfo, and ffprobe with its shared FFmpeg libraries. Yadifmod2 is included in the x86-64 bundles. The Apple Silicon bundle supports progressive sources and can use a separately installed ARM64 Yadifmod2-compatible plugin if you set `ENCODEASSISTANT_YADIF_PLUGIN`. The Intel macOS bundle has Yadifmod2 and can be run under Rosetta on Apple Silicon.

Third-party license texts and build inputs are described under `tools/notices`. Source archives and build scripts are also available alongside the desktop downloads on the release page.
