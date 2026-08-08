# Clippy

Clippy is a local proof-of-concept for turning long-form video into short-form
clips. It combines a React/Vite interface with a FastAPI backend for upload,
transcription, AI-assisted clip selection, caption generation, face-aware
framing, and MP4 rendering.

## What it does

- Upload MP4, MOV, WebM, or MKV source video.
- Extract audio with FFmpeg.
- Transcribe speech with Faster-Whisper.
- Use Groq-hosted language models to identify useful short-form moments.
- Detect persistent face anchors with OpenCV so clips can be framed around the
  likely speaker.
- Generate editable captions and ASS subtitle files.
- Render vertical or horizontal clips with FFmpeg.
- Run entirely as a local app; uploaded videos and rendered outputs stay in
  local `data/` folders.

## Tech stack

- Frontend: React, TypeScript, Vite, lucide-react
- Backend: FastAPI, Pydantic, Uvicorn
- Video/audio: FFmpeg and ffprobe
- Transcription: Faster-Whisper
- AI analysis: Groq API
- Face detection: OpenCV Haar cascade

## Requirements

- macOS, Linux, or another environment with Python, Node.js, and FFmpeg
- Python 3.10+
- Node.js 20+
- npm
- FFmpeg and ffprobe available on `PATH`
- Groq API key for semantic clip recommendations

## Local setup

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements.txt
npm install
```

Edit `.env` and set at least:

```bash
GROQ_API_KEY=your-groq-api-key
```

Optional fallback keys and model overrides are documented in `.env.example`.
Never commit `.env`; it is intentionally ignored by git.

## Run

```bash
npm run dev:all
```

Open `http://localhost:5173`. The command starts both FastAPI on port 8000 and
Vite on port 5173. Press `Ctrl+C` once to stop both processes.

The first transcription run may download the configured Faster-Whisper model.
Generated uploads, audio extracts, subtitles, and rendered clips are written to
`data/uploads/` and `data/outputs/`, both of which are ignored by git.

## macOS helper scripts

For a local macOS setup, double-click `bootstrap_clippy.command` once to create
the Python environment and install JavaScript packages. After setup,
double-click `run_clippy.command` to start the app.

To create a self-contained macOS ZIP for direct sharing:

```bash
./scripts/package_shareable.sh
```

The ZIP is written to `dist/Clippy-macOS.zip`. It includes local runtime
dependencies for convenience, but those generated package contents should not be
committed to the repository.

## Configuration

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | Primary Groq API key used for clip intelligence. |
| `GROQ_MODEL` | Primary Groq model name. |
| `GROQ_FALLBACK_API_KEY` | Optional fallback Groq API key. |
| `GROQ_FALLBACK_MODEL` | Optional fallback model name. |
| `WHISPER_MODEL` | Faster-Whisper model name, defaulting to `base`. |
| `UPLOAD_DIR` | Local upload/audio directory, defaulting to `./data/uploads`. |
| `OUTPUT_DIR` | Local render/subtitle directory, defaulting to `./data/outputs`. |

## Repository hygiene

This repository is prepared to exclude:

- API keys and local `.env` files
- virtual environments and `node_modules`
- uploaded source videos
- rendered video outputs and subtitle artifacts
- OS/editor noise and build caches

Before publishing changes, run:

```bash
git status --short
git diff --cached --stat
```

Only source, documentation, lockfiles, and intentional assets should be staged.

## License and attribution

Clippy is licensed under the Apache License 2.0. See `LICENSE`.

Attribution notices are provided in `NOTICE`. The bundled OpenCV Haar cascade
asset keeps its original Intel/OpenCV license header in
`backend/video/assets/haarcascade_frontalface_default.xml`.
