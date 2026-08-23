# K2S Downloader

## Environment
Tested on Python 3.10, Windows.
Not tested on others

## Note
For download corruption check to work, you should have ffmpeg available in environmental path.

## Installation
This project uses [uv](https://docs.astral.sh/uv/).

1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   (on Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`)
2. Download the repo
3. `uv sync`

## Usage
```
uv run main.py dl <link> --filename <filename> --split-size 20mb
```

`uv run` creates and updates the virtualenv automatically, so `uv sync` is optional.

Other subcommands:
```
uv run main.py ls          # list unfinished downloads
uv run main.py continue    # resume unfinished downloads
```
