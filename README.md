# Herald
### Ashborne AI Assistant — v0.1.0

> *Your voice, extended.*

---

## What this is

Herald is the voice-driven AI assistant at the core of the Ashborne suite.
This is the Phase 1 skeleton: a working STT → LLM → TTS pipeline you can
talk to from your PC right now.

```
You speak  →  Whisper transcribes  →  Claude reasons  →  ElevenLabs speaks
```

---

## Setup

### 1. Clone / place this folder somewhere permanent

```bash
cd ~/projects
# (this folder is already here)
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate      # Mac / Linux
.venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

Whisper also needs ffmpeg:
```bash
# Mac
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows — download from https://ffmpeg.org/download.html
```

### 4. Configure your keys

```bash
cp .env.example .env
```

Then open `.env` and fill in:
- `ANTHROPIC_API_KEY` — from console.anthropic.com
- `ELEVENLABS_API_KEY` — from elevenlabs.io (free tier works)

If you skip ElevenLabs, Herald falls back to `pyttsx3` (local TTS, no key needed):
```bash
pip install pyttsx3
```

### 5. Run Herald

```bash
python herald.py
```

---

## Voice commands

| You say | Herald does |
|---|---|
| Anything | Thinks and responds |
| `clear` | Wipes conversation history |
| `quit` / `goodbye herald` | Shuts down cleanly |

---

## Tuning

**Too sensitive / picking up background noise?**
Increase `SILENCE_THRESHOLD` in `.env` (default: `0.01`).

**Whisper too slow?**
Change `WHISPER_MODEL=tiny` in `.env`. Accuracy drops slightly.

**Want a different voice?**
Find your voice ID at elevenlabs.io/voice-lab and set `ELEVENLABS_VOICE_ID`.

---

## What's next (Phase 1 continuation)

- [ ] Tool use — web search, open apps, file operations
- [ ] Wake word detection (Porcupine) so Herald is always-on
- [ ] Persistent memory across sessions (ChromaDB)
- [ ] Herald API layer (prep for mobile companion)

---

## Project structure

```
herald/
├── herald.py          ← core pipeline (STT + LLM + TTS)
├── requirements.txt
├── .env.example       ← copy to .env and fill in keys
└── README.md
```

---

*Ashborne — built with purpose.*
