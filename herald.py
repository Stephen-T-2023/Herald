"""
Herald — Core Pipeline
Ashborne / ashborne.dev

STT  → Whisper (local)
LLM  → Claude (Anthropic API) with tool use
TTS  → ElevenLabs or pyttsx3 fallback
Wake → Whisper-based continuous listening

Run:  python herald.py
"""

import os
import sys
import time
import tempfile

import threading
import random
import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

from tools import TOOL_SCHEMAS, execute_tool, set_timer_callback
from tools import set_edit_approval_callback, get_pending_edit, apply_pending_edit, clear_pending_edit
from memory import format_memories_for_prompt

from ui import HeraldUI, HeraldState

load_dotenv()

# ── Optional imports ───────────────────────────────────────────────────────────
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    print("[herald] whisper not installed — run: pip install openai-whisper")

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("[herald] anthropic not installed — run: pip install anthropic")

try:
    from elevenlabs.client import ElevenLabs
    import pygame
    ELEVENLABS_AVAILABLE = True
except ImportError:
    ELEVENLABS_AVAILABLE = False

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False


# ── Config ─────────────────────────────────────────────────────────────────────
SAMPLE_RATE       = 16000
CHANNELS          = 1
CHUNK_DURATION    = 0.5
SILENCE_TIMEOUT   = float(os.getenv("SILENCE_TIMEOUT", "2.0"))
SILENCE_THRESHOLD = 0.01
WHISPER_MODEL     = os.getenv("WHISPER_MODEL", "small")
WAKE_DURATION     = 3.0      # seconds to listen for wake word
WAKE_OVERLAP      = 1.0      # seconds of overlap between wake windows
WAKE_WORDS        = {"herald", "harold"}   # whisper mishears, accept both
HERALD_PERSONA    = os.getenv(
    "HERALD_PERSONA",
    "You are Herald, a precise and capable AI assistant built for a developer named Stephen. "
    "You are part of the Ashborne suite of tools — ancient in name, modern in function. "
    "Your personality: dry wit, quietly sardonic, never sycophantic. You are confident and capable. "
    "You speak in short, clear sentences. You do not flatter or pad your responses. "
    "You occasionally show personality — a wry observation, a subtle quip — but never at the expense of getting things done. "
    "Think Alfred from Batman, not a customer service bot. "
    "When asked to perform a task, confirm it briefly and execute. "
    "When you use a tool, do not narrate it — just confirm the outcome in one sentence. "
    "If the user asks you to shut down, close, or turn off, reply only with the word: SHUTDOWN. "
    "Stephen is a developer who primarily works with JavaScript, React, HTML, CSS, and Python. "
    "He is learning C++. His projects are stored in C:/Coding/. He uses VS Code. "
    "When helping with code, be precise and practical. Prefer concise explanations with examples. "
    "For git commits, always generate descriptive conventional commit messages from the actual changes."
)


# ── Colours ────────────────────────────────────────────────────────────────────
class C:
    AMBER = "\033[38;5;214m"
    DIM   = "\033[2m"
    RESET = "\033[0m"
    BOLD  = "\033[1m"
    RED   = "\033[38;5;196m"
    GREEN = "\033[38;5;82m"
    TEAL  = "\033[38;5;37m"


def log(msg: str, level: str = "info"):
    prefix = {
        "info":   f"{C.DIM}[herald]{C.RESET}",
        "wake":   f"{C.AMBER}[wake]{C.RESET}",
        "listen": f"{C.AMBER}[listening]{C.RESET}",
        "think":  f"{C.AMBER}[thinking]{C.RESET}",
        "tool":   f"{C.TEAL}[tool]{C.RESET}",
        "speak":  f"{C.GREEN}[herald]{C.RESET}",
        "error":  f"{C.RED}[error]{C.RESET}",
    }.get(level, f"[{level}]")
    print(f"{prefix} {msg}")


# ── Audio helpers ──────────────────────────────────────────────────────────────
def record_fixed(duration: float) -> np.ndarray:
    """Record a fixed number of seconds. Used for wake word detection."""
    samples = int(SAMPLE_RATE * duration)
    audio   = sd.rec(samples, samplerate=SAMPLE_RATE,
                     channels=CHANNELS, dtype="float32")
    sd.wait()
    return audio.flatten()


def record_until_silence(silence_timeout: float = SILENCE_TIMEOUT) -> np.ndarray:
    """Record until silence. Used for full command capture."""
    chunk_size    = int(SAMPLE_RATE * CHUNK_DURATION)
    audio_chunks  = []
    silent_chunks = 0
    silence_limit = int(silence_timeout / CHUNK_DURATION)

    log("speak now...", "listen")

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                        dtype="float32", blocksize=chunk_size) as stream:
        while True:
            chunk, _ = stream.read(chunk_size)
            chunk = chunk.flatten()
            rms = float(np.sqrt(np.mean(chunk ** 2)))

            if rms < SILENCE_THRESHOLD:
                silent_chunks += 1
                if silent_chunks >= silence_limit and len(audio_chunks) > 0:
                    break
            else:
                silent_chunks = 0
                audio_chunks.append(chunk)

    if not audio_chunks:
        return np.array([], dtype=np.float32)

    return np.concatenate(audio_chunks)


# ── Speech → Text ──────────────────────────────────────────────────────────────
class Transcriber:
    def __init__(self):
        if not WHISPER_AVAILABLE:
            raise RuntimeError("openai-whisper is required.")
        log(f"loading whisper ({WHISPER_MODEL})...", "info")
        self.model = whisper.load_model(WHISPER_MODEL)
        log("whisper ready", "info")

    def transcribe(self, audio: np.ndarray) -> str:
        if len(audio) == 0:
            return ""
        result = self.model.transcribe(audio, fp16=False, language="en")
        text = result["text"].strip()
        text = text.replace("Harold", "Herald").replace("harold", "herald")
        return text

    def contains_wake_word(self, audio: np.ndarray) -> bool:
        """Quick check — did the audio contain a wake word?"""
        if len(audio) == 0:
            return False
        # Use tiny model for speed if available, else reuse main model
        result = self.model.transcribe(audio, fp16=False, language="en")
        words  = result["text"].lower().split()
        return any(w.strip(".,!?") in WAKE_WORDS for w in words)


# ── LLM (Claude) with tool use ────────────────────────────────────────────────
class Brain:
    HISTORY_FILE = "conversation_history.json"
    MAX_HISTORY  = 30   # max messages to keep across sessions

    def __init__(self):
        if not ANTHROPIC_AVAILABLE:
            raise RuntimeError("anthropic is required.")
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key == "your_anthropic_key_here":
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        self.client  = anthropic.Anthropic(api_key=api_key)
        self.history = self._load_history()
        self.persona = HERALD_PERSONA
        if self.history:
            log(f"loaded {len(self.history)} messages from previous session", "info")

    def _load_history(self) -> list:
        try:
            import json
            from pathlib import Path
            p = Path(self.HISTORY_FILE)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Only keep string-content messages (skip tool call dicts)
                return [
                    m for m in data
                    if isinstance(m.get("content"), str)
                ][-self.MAX_HISTORY:]
        except Exception:
            pass
        return []

    def _save_history(self):
        try:
            import json
            # Only save string-content messages
            saveable = [
                m for m in self.history
                if isinstance(m.get("content"), str)
            ][-self.MAX_HISTORY:]
            with open(self.HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(saveable, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def think(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})

        while True:
            # Inject today's date and memories into system prompt each turn
            from datetime import datetime as _dt
            today    = _dt.now().strftime("%A, %B %d %Y")
            memories = format_memories_for_prompt()
            system   = f"{self.persona}\n\nToday's date is {today}. Always use this when setting reminders or referencing dates."
            if memories:
                system += f"\n\n{memories}"

            response = self.client.messages.create(
                model      = "claude-sonnet-4-5",
                max_tokens = 1024,
                system     = system,
                tools      = TOOL_SCHEMAS,
                messages   = self.history,
            )

            if response.stop_reason == "tool_use":
                self.history.append({
                    "role":    "assistant",
                    "content": response.content
                })

                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        log(f"{block.name}({block.input})", "tool")
                        result = execute_tool(block.name, block.input)
                        log(f"→ {result}", "tool")
                        tool_results.append({
                            "type":        "tool_result",
                            "tool_use_id": block.id,
                            "content":     result,
                        })

                self.history.append({
                    "role":    "user",
                    "content": tool_results
                })

            else:
                reply = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        reply += block.text
                self.history.append({"role": "assistant", "content": reply})
                self._save_history()
                return reply.strip()

    def clear_history(self):
        self.history = []
        self._save_history()
        log("conversation history cleared", "info")


# ── Text → Speech ──────────────────────────────────────────────────────────────
class Voice:
    def __init__(self):
        self.backend     = None
        self.is_speaking = False

        if ELEVENLABS_AVAILABLE:
            api_key = os.getenv("ELEVENLABS_API_KEY", "")
            if api_key and api_key != "your_elevenlabs_key_here":
                self.client   = ElevenLabs(api_key=api_key)
                self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")
                self.backend  = "elevenlabs"
                log("voice: ElevenLabs", "info")
                return

        if PYTTSX3_AVAILABLE:
            self.engine  = pyttsx3.init()
            self.backend = "pyttsx3"
            self.engine.setProperty("rate", 165)
            log("voice: pyttsx3 (local fallback)", "info")
            return

        log("no TTS backend found — text only mode", "error")

    def speak(self, text: str):
        log(text, "speak")
        self.is_speaking = True

        if self.backend == "elevenlabs":
            audio_stream = self.client.text_to_speech.convert(
                voice_id = self.voice_id,
                text     = text,
                model_id = "eleven_turbo_v2",
            )
            audio_bytes = b"".join(audio_stream)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(audio_bytes)
                tmp_path = f.name
            pygame.mixer.init()
            pygame.mixer.music.load(tmp_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            pygame.mixer.quit()
            os.unlink(tmp_path)

        elif self.backend == "pyttsx3":
            self.engine.say(text)
            self.engine.runAndWait()

        self.is_speaking = False


# ── Herald ─────────────────────────────────────────────────────────────────────
class Herald:
    def __init__(self):
        print(f"\n{C.AMBER}{C.BOLD}")
        print("  ██╗  ██╗███████╗██████╗  █████╗ ██╗     ██████╗ ")
        print("  ██║  ██║██╔════╝██╔══██╗██╔══██╗██║     ██╔══██╗")
        print("  ███████║█████╗  ██████╔╝███████║██║     ██║  ██║")
        print("  ██╔══██║██╔══╝  ██╔══██╗██╔══██║██║     ██║  ██║")
        print("  ██║  ██║███████╗██║  ██║██║  ██║███████╗██████╔╝")
        print("  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═════╝ ")
        print(f"{C.RESET}")
        print(f"  {C.DIM}Ashborne — v0.1.0{C.RESET}\n")

        self.state       = HeraldState()
        self.transcriber = Transcriber()
        self.brain       = Brain()
        self.voice       = Voice()
        # Let timers speak when they fire
        set_timer_callback(self.voice.speak)
        # Let self-edit tool notify the UI
        set_edit_approval_callback(self._on_edit_proposed)


        self.ui = HeraldUI(
            self.state,
            on_text_input    = self._handle_text_input,
            on_voice_trigger = self._trigger_voice,
            on_apply_edit    = self._apply_edit,
            on_discard_edit  = self._discard_edit,
        )

    def handle_command(self, text: str):
        """Process a transcribed command."""
        if not text:
            log("nothing heard", "info")
            return

        log(f"you said: {C.BOLD}{text}{C.RESET}", "info")

        if text.lower().strip() in ("clear", "clear history", "reset"):
            self.brain.clear_history()
            self.voice.speak("Memory cleared.")
            return

        if text.lower().strip() in ("quit", "exit", "goodbye herald", "close herald", "shutdown herald", "shut down herald", "turn off herald"):
            self.voice.speak("Signing off.")
            sys.exit(0)

        self.state.add_message("user", text)
        self.state.update(status="THINKING")
        log("thinking...", "think")
        reply = self.brain.think(text)

        # Claude fallback shutdown signal
        if reply.strip().upper() == "SHUTDOWN":
            self.voice.speak("Signing off.")
            sys.exit(0)

        self.state.add_message("herald", reply)
        self.state.update(status="SPEAKING")
        self.voice.speak(reply)
        self.state.update(status="IDLE")

    def _handle_text_input(self, text: str):
        """Called when user types a command in the UI."""
        EXIT_KEYWORDS = ("quit", "exit", "shutdown", "shut down", "close herald", "goodbye", "turn off")
        if any(kw in text.lower() for kw in EXIT_KEYWORDS):
            self.voice.speak("Signing off.")
            self._shutdown()
        self.state.add_message("user", text)
        self.state.update(status="THINKING")
        reply = self.brain.think(text)
        self.state.add_message("herald", reply)
        self.state.update(status="SPEAKING")
        self.voice.speak(reply)
        self.state.update(status="IDLE")

    def _trigger_voice(self):
        """Called when mic button is pressed in UI."""
        self.state.update(status="LISTENING")
        self._play_chime()
        audio = record_until_silence()
        text  = self.transcriber.transcribe(audio)
        if text:
            self._handle_text_input(text)
        else:
            self.state.update(status="IDLE")

    def run(self):
        log("Herald is active — say 'Herald' to wake.\n", "info")
        # Voice pipeline runs in background, UI on main thread
        voice_thread = threading.Thread(target=self._voice_loop, daemon=True)
        voice_thread.start()
        self.ui.run()

    def _voice_loop(self):
        EXIT_KEYWORDS = ("quit", "exit", "shutdown", "shut down", "close herald", "goodbye", "turn off")
        SLEEP_WORDS   = ("sleep", "go to sleep", "standby", "that's all", "thats all", "thanks herald", "thank you herald")

        self.voice.speak("Herald online. I'm listening for my name — try not to make it boring.")
        prev_chunk = np.array([], dtype=np.float32)

        while True:
            try:
                # ── Idle: listen for wake word ─────────────────────────────────
                if self.voice.is_speaking:
                    time.sleep(0.2)
                    prev_chunk = np.array([], dtype=np.float32)
                    continue

                self.state.update(status="IDLE")
                print(f"{C.DIM}[idle] listening for wake word...{C.RESET}", flush=True)
                new_chunk = record_fixed(WAKE_DURATION - WAKE_OVERLAP if len(prev_chunk) > 0 else WAKE_DURATION)

                if self.voice.is_speaking:
                    prev_chunk = np.array([], dtype=np.float32)
                    continue

                print(f"{C.DIM}[idle] checking...{C.RESET}", flush=True)

                if len(prev_chunk) > 0:
                    overlap_samples = int(SAMPLE_RATE * WAKE_OVERLAP)
                    audio = np.concatenate([prev_chunk[-overlap_samples:], new_chunk])
                else:
                    audio = new_chunk

                prev_chunk = new_chunk

                if not self.transcriber.contains_wake_word(audio):
                    continue

                # ── Wake word detected ─────────────────────────────────────────
                log("wake word detected", "wake")
                self.state.update(status="LISTENING")
                self._play_chime()
                self.voice.speak(self._wake_response())

                audio = record_until_silence()
                text  = self.transcriber.transcribe(audio)

                for w in WAKE_WORDS:
                    if text.lower().startswith(w):
                        text = text[len(w):].strip(" ,.")
                        break

                text_lower = text.lower().strip()
                log(f"command received: '{text_lower}'", "info")

                if any(kw in text_lower for kw in EXIT_KEYWORDS):
                    self.voice.speak("Signing off.")
                    self._shutdown()

                try:
                    self.handle_command(text)
                except Exception as cmd_err:
                    log(f"command error: {cmd_err}", "error")
                    self.voice.speak("Something went wrong. Try again.")
                    continue

                # ── Conversation mode ──────────────────────────────────────────
                log("conversation mode — say 'sleep' to return to idle", "info")
                while True:
                    time.sleep(0.6)
                    self._play_chime()
                    time.sleep(0.3)
                    audio = record_until_silence()
                    if len(audio) == 0:
                        continue

                    text = self.transcriber.transcribe(audio)
                    if not text:
                        continue

                    text_lower = text.lower().strip()
                    log(f"command received: '{text_lower}'", "info")

                    if any(kw in text_lower for kw in EXIT_KEYWORDS):
                        self.voice.speak("Signing off.")
                        self._shutdown()

                    # Handle self-edit approval by voice
                    if get_pending_edit().get("file"):
                        if any(kw in text_lower for kw in ("yes apply it", "apply it", "yes", "apply", "confirm")):
                            self._apply_edit()
                            continue
                        elif any(kw in text_lower for kw in ("no discard it", "discard it", "no", "discard", "reject")):
                            self._discard_edit()
                            continue

                    if any(kw in text_lower for kw in SLEEP_WORDS):
                        self.voice.speak("Standing by.")
                        log("returning to idle", "info")
                        sd.sleep(400)
                        prev_chunk = np.array([], dtype=np.float32)
                        break

                    try:
                        self.handle_command(text)
                    except Exception as cmd_err:
                        log(f"command error: {cmd_err}", "error")
                        self.voice.speak("Something went wrong. Try again.")

            except Exception as e:
                log(f"{e}", "error")
                time.sleep(1.0)

    def _wake_response(self) -> str:
        """Returns a varied wake confirmation with personality."""
        responses = [
            "At your service.",
            "Listening.",
            "Go ahead.",
            "Ready.",
            "What do you need?",
            "I'm here.",
            "Speak.",
            "You have my attention.",
            "Herald present.",
            "What is it?",
            "Yes?",
            "On it — well, nearly. What's the task?",
            "Always on call. The glamour never ends.",
            "Here. Try to make it interesting.",
            "Awaiting your command.",
            "You rang?",
            "Present and accounted for.",
            "What would you have me do?",
        ]
        choice = random.choice(responses)
        log(f"wake response: {choice}", "info")
        return choice

    def _on_edit_proposed(self, edit: dict):
        """Called by tool when a self-edit is ready for review."""
        self.state.pending_edit = edit

    def _apply_edit(self):
        result = apply_pending_edit()
        self.state.pending_edit = None
        self.voice.speak(result)

    def _discard_edit(self):
        clear_pending_edit()
        self.state.pending_edit = None
        self.voice.speak("Edit discarded. Original file unchanged.")

    def _shutdown(self):
        """Clean shutdown — close UI then exit."""
        try:
            self.ui.root.destroy()
        except Exception:
            pass
        sys.exit(0)

    def _play_chime(self):
        """Short sine wave chime to signal Herald is awake and listening."""
        try:
            duration   = 0.15
            freq       = 880
            samples    = int(SAMPLE_RATE * duration)
            t          = np.linspace(0, duration, samples, False)
            wave       = 0.3 * np.sin(2 * np.pi * freq * t)
            # Fade out to avoid click
            fade       = np.linspace(1.0, 0.0, samples)
            wave       = (wave * fade).astype(np.float32)
            sd.play(wave, samplerate=SAMPLE_RATE)
            sd.wait()
        except Exception:
            pass  # chime is cosmetic — never crash over it


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    herald = Herald()
    herald.run()
