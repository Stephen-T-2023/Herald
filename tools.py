"""
Herald — Tool Definitions
Ashborne / ashborne.dev

Each tool is:
  1. A schema (tells Claude what the tool does and what args it takes)
  2. A handler (actually executes the action on the PC)
"""

import os
import sys
import subprocess
import webbrowser
import platform
import threading
import time
from datetime import datetime
from pathlib import Path


# ── Platform ───────────────────────────────────────────────────────────────────
WINDOWS = platform.system() == "Windows"
MAC     = platform.system() == "Darwin"
LINUX   = platform.system() == "Linux"

# ── Active timers registry ─────────────────────────────────────────────────────
_active_timers: dict[str, threading.Timer] = {}
_timer_callback = None   # set by Herald after init so timer can speak

def set_timer_callback(fn):
    global _timer_callback
    _timer_callback = fn


# ── Tool schemas (sent to Claude) ─────────────────────────────────────────────
TOOL_SCHEMAS = [
    {
        "name": "open_application",
        "description": (
            "Opens an application on the user's PC. Use when the user asks to open, "
            "launch, or start a program, app, or software."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "The name of the application to open, e.g. 'VS Code', 'Spotify', 'Chrome'."
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Searches the web and returns a summary of the top results. Use when the user "
            "asks to search for something, look something up, or find information online."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "open_url",
        "description": "Opens a URL in the default web browser.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The full URL to open."}
            },
            "required": ["url"]
        }
    },
    {
        "name": "file_search",
        "description": "Searches for files or folders on the user's PC by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "File or folder name to search for."},
                "search_path": {"type": "string", "description": "Where to search. Defaults to home directory.", "default": ""}
            },
            "required": ["name"]
        }
    },
    {
        "name": "create_folder",
        "description": "Creates a new folder at the specified path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full path of the folder to create."}
            },
            "required": ["path"]
        }
    },
    {
        "name": "system_control",
        "description": "Controls system-level settings like volume or getting system info.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["volume_up", "volume_down", "mute", "system_info"],
                    "description": "The system action to perform."
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "get_time",
        "description": "Returns the current time and/or date. Use when the user asks what time or date it is.",
        "input_schema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["time", "date", "both"],
                    "description": "Whether to return time, date, or both.",
                    "default": "both"
                }
            },
            "required": []
        }
    },
    {
        "name": "set_timer",
        "description": (
            "Sets a countdown timer that speaks aloud when it expires. "
            "Use when the user asks to set a timer, remind them in X minutes, or count down."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "duration_seconds": {
                    "type": "integer",
                    "description": "Timer duration in seconds. Convert minutes/hours to seconds first."
                },
                "label": {
                    "type": "string",
                    "description": "Optional label for the timer, e.g. 'tea', 'standup'. Defaults to 'Timer'.",
                    "default": "Timer"
                }
            },
            "required": ["duration_seconds"]
        }
    },
    {
        "name": "cancel_timer",
        "description": "Cancels an active timer by label.",
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "Label of the timer to cancel. Use 'all' to cancel all timers."
                }
            },
            "required": ["label"]
        }
    },
    {
        "name": "spotify_control",
        "description": (
            "Controls Spotify playback. Use for play, pause, skip, previous, volume, "
            "or searching for and playing a specific song, artist, or playlist."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "previous", "volume_up", "volume_down", "current", "search_play"],
                    "description": "The Spotify action to perform."
                },
                "query": {
                    "type": "string",
                    "description": "For search_play: the song, artist, or playlist to search for and play."
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "daily_briefing",
        "description": (
            "Delivers the daily briefing — time, date, weather, reminders and news. "
            "Use when the user says 'good morning', 'morning briefing', or 'daily briefing'."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "add_reminder",
        "description": (
            "Sets a reminder for a specific date. Use when the user says 'remind me on [date] to...' "
            "or 'remember to remind me on [date]'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "What to remind the user about."
                },
                "date": {
                    "type": "string",
                    "description": "The date to remind on, in YYYY-MM-DD format."
                }
            },
            "required": ["text", "date"]
        }
    },
    {
        "name": "list_reminders",
        "description": "Lists all upcoming reminders. Use when the user asks what reminders they have.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "delete_reminder",
        "description": "Deletes a reminder matching the given text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text matching the reminder to delete."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_weather",
        "description": "Gets current weather for a specific city or all configured cities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, e.g. 'Bristol,UK'. Leave empty for all configured cities."
                }
            },
            "required": []
        }
    },
    {
        "name": "system_monitor",
        "description": (
            "Returns current system performance stats — CPU, RAM, GPU, disk usage and temperatures. "
            "Use when the user asks how the PC is running, CPU usage, memory usage, or system stats."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["all", "cpu", "ram", "gpu", "disk", "temp"],
                    "description": "Which metric to check. Use 'all' for a full overview.",
                    "default": "all"
                }
            },
            "required": []
        }
    },
    {
        "name": "remember",
        "description": (
            "Saves something to Herald's persistent memory. Use when the user says "
            "'remember that', 'remember this', 'don't forget', or 'keep in mind'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The exact thing to remember, stated clearly and concisely."
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "forget",
        "description": (
            "Removes something from Herald's persistent memory. Use when the user says "
            "'forget that', 'forget everything', or 'don't remember X anymore'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to forget. Use 'all' or 'everything' to clear all memories."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_memories",
        "description": "Lists everything Herald currently remembers. Use when the user asks what you remember.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },

    {
        "name": "run_command",
        "description": (
            "Runs a terminal command or script on the user's PC. "
            "Use when the user asks to run a command, script, dev server, git operation, or terminal task."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to run, e.g. 'git status', 'npm run dev', 'python script.py'."
                },
                "working_dir": {
                    "type": "string",
                    "description": "Directory to run the command in. Defaults to user home if not specified.",
                    "default": ""
                },
                "background": {
                    "type": "boolean",
                    "description": "If true, runs the command in a new terminal window and doesn't wait for it to finish. Use for servers and long-running processes.",
                    "default": False
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": (
            "Reads a file and returns its contents. Use when the user asks to read, open, "
            "summarise or explain a file — code, text, markdown, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Full path to the file to read."
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to return. Defaults to 200.",
                    "default": 200
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": (
            "Writes or appends content to a file. Use when the user asks to save, write, "
            "create or append to a file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Full path to the file to write."
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file."
                },
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "description": "Whether to overwrite or append. Defaults to overwrite.",
                    "default": "overwrite"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "clipboard",
        "description": "Reads from or writes to the system clipboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write"],
                    "description": "Whether to read from or write to the clipboard."
                },
                "content": {
                    "type": "string",
                    "description": "For write: the content to copy to the clipboard.",
                    "default": ""
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "create_repo",
        "description": (
            "Creates a new git repository locally and on GitHub. "
            "Use when the user asks to create a new repo, initialise a project, or start a new git project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Repository name, e.g. 'my-project'."
                },
                "description": {
                    "type": "string",
                    "description": "Short description of the repository.",
                    "default": ""
                },
                "private": {
                    "type": "boolean",
                    "description": "Whether the repo should be private. Defaults to False (public).",
                    "default": False
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "git_command",
        "description": (
            "Runs git operations by voice. Handles status, log, pull, push, commit, branch, diff. "
            "For commits, automatically generates a descriptive commit message from the diff. "
            "Use when the user asks to commit, push, pull, check git status, view log, or manage branches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "log", "diff", "pull", "push", "commit", "commit_push", "branch", "checkout", "add_all"],
                    "description": "The git action to perform."
                },
                "project": {
                    "type": "string",
                    "description": "Project folder name under C:\\Coding\\. Leave empty to use current context.",
                    "default": ""
                },
                "message": {
                    "type": "string",
                    "description": "Commit message. If not provided for commit actions, Herald will generate one from the diff.",
                    "default": ""
                },
                "branch": {
                    "type": "string",
                    "description": "Branch name for checkout action.",
                    "default": ""
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "open_project",
        "description": (
            "Opens a project folder in VS Code. Use when the user asks to open a project, "
            "open VS Code for a project, or start working on something."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project folder name under C:\\Coding\\, e.g. 'Herald', 'my-react-app'."
                }
            },
            "required": ["project"]
        }
    },
    {
        "name": "explain_code",
        "description": (
            "Reads a code file and explains what it does, or explains a specific function or error. "
            "Use when the user asks to explain a file, what a function does, or what an error means."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Full path to the file to explain."
                },
                "focus": {
                    "type": "string",
                    "description": "Optional — specific function, class, or error to focus on.",
                    "default": ""
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "find_project_file",
        "description": (
            "Finds a file within the user's coding projects. Use when the user mentions a filename "
            "without a full path, or asks to find a file in their projects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Filename or partial name to search for, e.g. 'App.jsx', 'index.py'."
                },
                "project": {
                    "type": "string",
                    "description": "Optional project name to narrow the search.",
                    "default": ""
                }
            },
            "required": ["filename"]
        }
    },
    {
        "name": "self_edit",
        "description": (
            "Proposes an edit to one of Herald's own source files. "
            "Reads the file, drafts a change, shows a diff for approval, and only applies it if the user confirms. "
            "Use when the user asks Herald to improve, fix, or modify its own code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Herald source file to edit, e.g. 'tools.py', 'herald.py', 'ui.py'."
                },
                "instruction": {
                    "type": "string",
                    "description": "What change to make, described clearly."
                }
            },
            "required": ["file", "instruction"]
        }
    },
    {
        "name": "steam_launch",
        "description": (
            "Launches a Steam game by name. Use when the user asks to open, play, or launch a game. "
            "Searches the user's installed Steam library automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "game_name": {
                    "type": "string",
                    "description": "The name of the game to launch, e.g. 'Elden Ring', 'Cyberpunk', 'CS2'."
                }
            },
            "required": ["game_name"]
        }
    },
    {
        "name": "window_management",
        "description": (
            "Controls application windows — minimise, maximise, close, focus, or minimise all. "
            "Use when the user asks to switch to, focus, minimise, maximise, or close a window."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["minimise_all", "focus", "minimise", "maximise", "close"],
                    "description": "The window action to perform."
                },
                "app_name": {
                    "type": "string",
                    "description": "For focus/minimise/maximise/close: the name of the app window to target."
                }
            },
            "required": ["action"]
        }
    },
]


# ── App name → executable mapping (Windows) ───────────────────────────────────
APP_MAP_WINDOWS = {
    "vs code":        "code",
    "vscode":         "code",
    "visual studio code": "code",
    "notepad":        "notepad",
    "notepad++":      "notepad++",
    "chrome":         "chrome",
    "google chrome":  "chrome",
    "firefox":        "firefox",
    "spotify":        "spotify",
    "discord":        "discord",
    "slack":          "slack",
    "explorer":       "explorer",
    "file explorer":  "explorer",
    "terminal":       "wt",
    "powershell":     "powershell",
    "cmd":            "cmd",
    "task manager":   "taskmgr",
    "calculator":     "calc",
    "paint":          "mspaint",
    "word":           "winword",
    "excel":          "excel",
    "outlook":        "outlook",
    "teams":          "teams",
    "obs":            "obs64",
    "steam":          "steam",
    "minecraft":      "C:\\XboxGames\\Minecraft Launcher\\Content\\Minecraft.exe",
    "notion":         "notion",
    "figma":          "figma",
    "postman":        "postman",
}

APP_MAP_MAC = {
    "vs code":        "Visual Studio Code",
    "vscode":         "Visual Studio Code",
    "chrome":         "Google Chrome",
    "firefox":        "Firefox",
    "spotify":        "Spotify",
    "discord":        "Discord",
    "slack":          "Slack",
    "terminal":       "Terminal",
    "finder":         "Finder",
    "safari":         "Safari",
    "notes":          "Notes",
    "calculator":     "Calculator",
    "word":           "Microsoft Word",
    "excel":          "Microsoft Excel",
    "notion":         "Notion",
    "figma":          "Figma",
}


# ── Spotify client (lazy init) ─────────────────────────────────────────────────
_spotify = None

def _get_spotify():
    global _spotify
    if _spotify is not None:
        return _spotify
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        from dotenv import load_dotenv
        load_dotenv()
        _spotify = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id     = os.getenv("SPOTIFY_CLIENT_ID"),
            client_secret = os.getenv("SPOTIFY_CLIENT_SECRET"),
            redirect_uri  = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback"),
            scope         = "user-modify-playback-state user-read-playback-state user-read-currently-playing user-library-read playlist-read-private",
            cache_path    = ".spotify_cache"
        ))
        return _spotify
    except Exception as e:
        return None


# ── Tool handlers ──────────────────────────────────────────────────────────────

def handle_open_application(app_name: str) -> str:
    name_lower = app_name.lower().strip()
    if WINDOWS:
        exe = APP_MAP_WINDOWS.get(name_lower, name_lower)
        try:
            # Check if it's a full path (contains :\ or starts with \)
            if ":\" in exe or exe.startswith("\\"):
                # Full path - check if file exists
                if os.path.exists(exe):
                    subprocess.Popen(f'"{exe}"', shell=True)
                    return f"Opened {app_name}."
                else:
                    return f"Application '{app_name}' not found at path: {exe}"
            else:
                # Regular executable name - check PATH
                result = subprocess.run(
                    f'where "{exe}"', shell=True,
                    capture_output=True, text=True, timeout=3
                )
                if result.returncode != 0 and name_lower not in APP_MAP_WINDOWS:
                    return f"Application '{app_name}' not found. It may not be installed or not in PATH."
                subprocess.Popen(exe, shell=True)
                return f"Opened {app_name}."
        except subprocess.TimeoutExpired:
            return f"Timed out trying to find {app_name}."
        except Exception as e:
            return f"Could not open {app_name}: {e}"
    elif MAC:
        app = APP_MAP_MAC.get(name_lower, app_name)
        try:
            subprocess.Popen(["open", "-a", app])
            return f"Opened {app_name}."
        except Exception as e:
            return f"Could not open {app_name}: {e}"
    elif LINUX:
        try:
            subprocess.Popen([name_lower])
            return f"Opened {app_name}."
        except Exception as e:
            return f"Could not open {app_name}: {e}"
    return "Platform not supported."



def handle_web_search(query: str) -> str:
    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    webbrowser.open(search_url)
    return f"Opened a Google search for: {query}. Let the user know you've opened it in their browser."


def handle_open_url(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url} in the browser."


def handle_file_search(name: str, search_path: str = "") -> str:
    base = Path(search_path) if search_path else Path.home()
    matches = []
    try:
        for p in base.rglob(f"*{name}*"):
            matches.append(str(p))
            if len(matches) >= 5:
                break
    except PermissionError:
        pass
    if not matches:
        return f"No files matching '{name}' found under {base}."
    result = f"Found {len(matches)} match(es) for '{name}':\n"
    result += "\n".join(matches)
    return result


def handle_create_folder(path: str) -> str:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return f"Created folder: {path}"
    except Exception as e:
        return f"Could not create folder: {e}"


def handle_system_control(action: str) -> str:
    if action == "system_info":
        info = (
            f"OS: {platform.system()} {platform.release()}, "
            f"Machine: {platform.machine()}, "
            f"Processor: {platform.processor()}"
        )
        return info
    if WINDOWS:
        if action == "volume_up":
            subprocess.run(["powershell", "-c",
                "$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys([char]175)"],
                capture_output=True)
            return "Volume increased."
        elif action == "volume_down":
            subprocess.run(["powershell", "-c",
                "$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys([char]174)"],
                capture_output=True)
            return "Volume decreased."
        elif action == "mute":
            subprocess.run(["powershell", "-c",
                "$obj = New-Object -ComObject WScript.Shell; $obj.SendKeys([char]173)"],
                capture_output=True)
            return "Toggled mute."
    elif MAC:
        if action == "volume_up":
            subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) + 10)"])
            return "Volume increased."
        elif action == "volume_down":
            subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) - 10)"])
            return "Volume decreased."
        elif action == "mute":
            subprocess.run(["osascript", "-e", "set volume with output muted"])
            return "Muted."
    return f"Action '{action}' not supported on this platform."


def handle_get_time(format: str = "both") -> str:
    now = datetime.now()
    time_str = now.strftime("%I:%M %p").lstrip("0")
    date_str = now.strftime("%A, %B %d %Y")
    if format == "time":
        return f"The current time is {time_str}."
    elif format == "date":
        return f"Today is {date_str}."
    else:
        return f"It is {time_str} on {date_str}."


def handle_set_timer(duration_seconds: int, label: str = "Timer") -> str:
    label = label.strip() or "Timer"

    def _fire():
        _active_timers.pop(label, None)
        if _timer_callback:
            _timer_callback(f"{label} complete.")

    if label in _active_timers:
        _active_timers[label].cancel()

    t = threading.Timer(duration_seconds, _fire)
    t.daemon = True
    t.start()
    _active_timers[label] = t

    minutes, seconds = divmod(duration_seconds, 60)
    hours,   minutes = divmod(minutes, 60)

    parts = []
    if hours:   parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
    if minutes: parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
    if seconds: parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")

    duration_str = ", ".join(parts)
    return f"{label} set for {duration_str}."


def handle_cancel_timer(label: str) -> str:
    if label.lower() == "all":
        for t in _active_timers.values():
            t.cancel()
        _active_timers.clear()
        return "All timers cancelled."
    if label in _active_timers:
        _active_timers[label].cancel()
        _active_timers.pop(label)
        return f"{label} timer cancelled."
    return f"No active timer named '{label}'."


def handle_spotify_control(action: str, query: str = "") -> str:
    sp = _get_spotify()
    if not sp:
        return "Spotify is not configured. Check your SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env."

    try:
        devices     = sp.devices()
        device_list = devices.get("devices", [])
        # Prefer active device, fall back to any available device
        active    = next((d for d in device_list if d["is_active"]), None)
        available = device_list[0] if device_list else None
        device    = active or available
        device_id = device["id"] if device else None
        if not device_id:
            return "No Spotify device found. Open Spotify and play something briefly first."

        if action == "play":
            sp.start_playback(device_id=device_id)
            return "Playback resumed."

        elif action == "pause":
            sp.pause_playback(device_id=device_id)
            return "Playback paused."

        elif action == "next":
            sp.next_track(device_id=device_id)
            return "Skipped to next track."

        elif action == "previous":
            sp.previous_track(device_id=device_id)
            return "Went back to previous track."

        elif action == "volume_up":
            current = sp.current_playback()
            vol = min(100, (current["device"]["volume_percent"] + 10)) if current else 60
            sp.volume(vol, device_id=device_id)
            return f"Spotify volume set to {vol}%."

        elif action == "volume_down":
            current = sp.current_playback()
            vol = max(0, (current["device"]["volume_percent"] - 10)) if current else 40
            sp.volume(vol, device_id=device_id)
            return f"Spotify volume set to {vol}%."

        elif action == "current":
            current = sp.current_playback()
            if current and current.get("item"):
                track   = current["item"]["name"]
                artists = ", ".join(a["name"] for a in current["item"]["artists"])
                status  = "Playing" if current["is_playing"] else "Paused"
                return f"{status}: {track} by {artists}."
            return "Nothing is currently playing."

        elif action == "search_play":
            if not query:
                return "No search query provided."

            q_lower = query.lower()

            # 1. Check user's playlists first
            playlists = sp.current_user_playlists(limit=50)
            for pl in playlists.get("items", []):
                if pl and q_lower in pl["name"].lower():
                    sp.start_playback(device_id=device_id, context_uri=pl["uri"])
                    return f"Playing your playlist: {pl['name']}."

            # 2. Try artist search — if found, shuffle their top tracks
            artist_results = sp.search(q=query, limit=1, type="artist")
            artists = artist_results.get("artists", {}).get("items", [])
            if artists and artists[0].get("popularity", 0) > 20:
                artist = artists[0]
                # Play artist context with shuffle on — plays full catalogue
                sp.shuffle(True, device_id=device_id)
                sp.start_playback(device_id=device_id, context_uri=artist["uri"])
                return f"Shuffling {artist['name']}."

            # 3. Fall back to track search
            results = sp.search(q=query, limit=1, type="track")
            tracks  = results.get("tracks", {}).get("items", [])
            if not tracks:
                return f"No results found for '{query}'."
            uri    = tracks[0]["uri"]
            name   = tracks[0]["name"]
            artist = tracks[0]["artists"][0]["name"]
            sp.start_playback(device_id=device_id, uris=[uri])
            return f"Playing {name} by {artist}."

    except Exception as e:
        return f"Spotify error: {e}"

    return "Unknown Spotify action."


def handle_window_management(action: str, app_name: str = "") -> str:
    try:
        import pygetwindow as gw

        if action == "minimise_all":
            if WINDOWS:
                subprocess.run(["powershell", "-c",
                    "$shell = New-Object -ComObject Shell.Application; $shell.MinimizeAll()"],
                    capture_output=True)
                return "All windows minimised."
            else:
                for w in gw.getAllWindows():
                    try: w.minimize()
                    except: pass
                return "All windows minimised."

        if not app_name:
            return "Please specify an app name for this action."

        # Find matching window
        matches = [w for w in gw.getAllWindows()
                   if app_name.lower() in w.title.lower() and w.title.strip()]

        if not matches:
            return f"No window found matching '{app_name}'."

        window = matches[0]

        if action == "focus":
            window.activate()
            return f"Focused {window.title}."

        elif action == "minimise":
            window.minimize()
            return f"Minimised {window.title}."

        elif action == "maximise":
            window.maximize()
            return f"Maximised {window.title}."

        elif action == "close":
            window.close()
            return f"Closed {window.title}."

    except ImportError:
        return "pygetwindow is not installed. Run: pip install pygetwindow"
    except Exception as e:
        return f"Window management error: {e}"

    return "Unknown window action."


# ── Briefing & reminders ──────────────────────────────────────────────────────
def handle_daily_briefing() -> str:
    from briefing import get_briefing
    return get_briefing()

def handle_add_reminder(text: str, date: str) -> str:
    from briefing import add_reminder
    return add_reminder(text, date)

def handle_list_reminders() -> str:
    from briefing import list_reminders
    reminders = list_reminders()
    if not reminders:
        return "No upcoming reminders."
    lines = [f"- {r['date']}: {r['text']}" for r in reminders]
    return "Upcoming reminders:\n" + "\n".join(lines)

def handle_delete_reminder(query: str) -> str:
    from briefing import delete_reminder
    return delete_reminder(query)

def handle_get_weather(city: str = "") -> str:
    from briefing import get_weather, get_all_weather
    if city:
        return get_weather(city)
    return get_all_weather()


# ── System monitor ────────────────────────────────────────────────────────────
def handle_system_monitor(metric: str = "all") -> str:
    try:
        import psutil
    except ImportError as e:
        return f"psutil import failed: {e}"

    parts = []

    if metric in ("all", "cpu"):
        cpu_pct  = psutil.cpu_percent(interval=0.5)
        cpu_freq = psutil.cpu_freq()
        freq_str = f" @ {cpu_freq.current:.0f}MHz" if cpu_freq else ""
        parts.append(f"CPU: {cpu_pct:.0f}%{freq_str}")

    if metric in ("all", "ram"):
        ram = psutil.virtual_memory()
        parts.append(
            f"RAM: {ram.percent:.0f}% used "
            f"({ram.used / 1e9:.1f}GB / {ram.total / 1e9:.1f}GB)"
        )

    if metric in ("all", "disk"):
        disk = psutil.disk_usage("/")
        parts.append(
            f"Disk: {disk.percent:.0f}% used "
            f"({disk.used / 1e9:.1f}GB / {disk.total / 1e9:.1f}GB)"
        )

    if metric in ("all", "temp"):
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    for e in entries[:1]:
                        parts.append(f"Temp ({name}): {e.current:.0f}°C")
            else:
                parts.append("Temp: not available on this platform")
        except AttributeError:
            parts.append("Temp: not available on Windows via psutil")

    if metric in ("all", "gpu"):
        try:
            import GPUtil
            gpus = GPUtil.getGPUs()
            if gpus:
                for gpu in gpus:
                    parts.append(
                        f"GPU: {gpu.name} — {gpu.load * 100:.0f}% load, "
                        f"{gpu.memoryUsed:.0f}MB / {gpu.memoryTotal:.0f}MB VRAM, "
                        f"{gpu.temperature:.0f}°C"
                    )
            else:
                parts.append("GPU: none detected")
        except ImportError:
            parts.append("GPU: GPUtil not installed")
        except Exception as e:
            parts.append(f"GPU: unavailable ({e})")

    if not parts:
        return "No metrics available."

    return " | ".join(parts)


# ── Memory ────────────────────────────────────────────────────────────────────
def handle_remember(content: str) -> str:
    from memory import add_memory
    return add_memory(content)

def handle_forget(query: str) -> str:
    from memory import forget_memory
    return forget_memory(query)

def handle_list_memories() -> str:
    from memory import get_all_memories
    mems = get_all_memories()
    if not mems:
        return "No memories stored."
    lines = [f"- {m['content']}" for m in mems]
    return "I currently remember:\n" + "\n".join(lines)





# ── Terminal & files ──────────────────────────────────────────────────────────
def handle_run_command(command: str, working_dir: str = "", background: bool = False) -> str:
    import subprocess
    from pathlib import Path

    cwd = working_dir if working_dir and Path(working_dir).exists() else str(Path.home())

    try:
        if background:
            if WINDOWS:
                subprocess.Popen(
                    f'start cmd /K "{command}"',
                    shell=True, cwd=cwd
                )
            else:
                subprocess.Popen(
                    f'open -a Terminal --args -c "{command}"',
                    shell=True, cwd=cwd
                )
            return f"Running in new terminal: {command}"
        else:
            result = subprocess.run(
                command, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=30
            )
            output = result.stdout.strip() or result.stderr.strip()
            if not output:
                return f"Command completed with exit code {result.returncode}."
            # Trim long output
            lines = output.splitlines()
            if len(lines) > 30:
                output = "\n".join(lines[:30]) + f"\n... ({len(lines) - 30} more lines)"
            return output
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Command error: {e}"


def handle_read_file(path: str, max_lines: int = 200) -> str:
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return f"File not found: {path}"
    if not p.is_file():
        return f"Not a file: {path}"
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) > max_lines:
            content = "".join(lines[:max_lines])
            return content + f"\n... ({len(lines) - max_lines} more lines, {p.name})"
        return "".join(lines)
    except Exception as e:
        return f"Could not read file: {e}"


def handle_write_file(path: str, content: str, mode: str = "overwrite") -> str:
    from pathlib import Path
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        write_mode = "a" if mode == "append" else "w"
        with open(p, write_mode, encoding="utf-8") as f:
            f.write(content)
        return f"{'Appended to' if mode == 'append' else 'Written to'} {path}."
    except Exception as e:
        return f"Could not write file: {e}"


def handle_clipboard(action: str, content: str = "") -> str:
    try:
        import subprocess
        if action == "read":
            if WINDOWS:
                result = subprocess.run(
                    ["powershell", "-c", "Get-Clipboard"],
                    capture_output=True, text=True
                )
                return result.stdout.strip() or "Clipboard is empty."
            elif MAC:
                result = subprocess.run(["pbpaste"], capture_output=True, text=True)
                return result.stdout.strip() or "Clipboard is empty."
        elif action == "write":
            if not content:
                return "No content provided to copy."
            if WINDOWS:
                subprocess.run(
                    ["powershell", "-c", f"Set-Clipboard -Value '{content}'"],
                    capture_output=True
                )
            elif MAC:
                subprocess.run(["pbcopy"], input=content.encode(), capture_output=True)
            return f"Copied to clipboard: {content[:50]}{'...' if len(content) > 50 else ''}"
    except Exception as e:
        return f"Clipboard error: {e}"
    return "Unknown clipboard action."


# ── Coding assistant ──────────────────────────────────────────────────────────
CODING_ROOT = "C:/Coding"


def _find_project_path(project: str) -> str:
    """Find a project folder under C:/Coding."""
    from pathlib import Path
    root = Path(CODING_ROOT)
    if not project:
        return CODING_ROOT

    # Exact match
    exact = root / project
    if exact.exists():
        return str(exact)

    # Case-insensitive partial match
    try:
        for p in root.iterdir():
            if p.is_dir() and project.lower() in p.name.lower():
                return str(p)
    except Exception:
        pass

    return CODING_ROOT


def _get_git_exe() -> str:
    """Find git executable — checks PATH then common Windows install locations."""
    import shutil
    git = shutil.which("git")
    if git:
        return git
    candidates = [
        "C:/Program Files/Git/cmd/git.exe",
        "C:/Program Files (x86)/Git/cmd/git.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "git"


def _run_git(args: list, cwd: str) -> str:
    """Run a git command and return output."""
    import subprocess
    git_exe = _get_git_exe()
    try:
        result = subprocess.run(
            [git_exe] + args, cwd=cwd,
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip() or result.stderr.strip()
        return output or "Done."
    except subprocess.TimeoutExpired:
        return "Git command timed out."
    except FileNotFoundError:
        return "Git not found. Make sure git is installed and in PATH."
    except Exception as e:
        return f"Git error: {e}"


def _generate_commit_message(cwd: str) -> str:
    """Use Claude to generate a commit message from the current diff."""
    import subprocess
    import anthropic
    import os
    from dotenv import load_dotenv
    load_dotenv()

    try:
        diff = subprocess.run(
            ["git", "diff", "--staged"],
            cwd=cwd, capture_output=True, text=True, timeout=10
        ).stdout.strip()

        if not diff:
            # Try unstaged diff
            diff = subprocess.run(
                ["git", "diff"],
                cwd=cwd, capture_output=True, text=True, timeout=10
            ).stdout.strip()

        if not diff:
            return "No changes to commit."

        # Trim very large diffs
        if len(diff) > 4000:
            diff = diff[:4000] + "\n... (truncated)"

        client   = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model      = "claude-sonnet-4-5",
            max_tokens = 100,
            messages   = [{
                "role": "user",
                "content": (
                    f"Write a concise git commit message (under 72 chars) for this diff. "
                    f"Use conventional commit format (feat/fix/refactor/docs/style/chore). "
                    f"Reply with just the message, nothing else.\n\n{diff}"
                )
            }]
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"chore: update files"


def handle_git_command(action: str, project: str = "", message: str = "", branch: str = "") -> str:
    cwd = _find_project_path(project)

    if action == "status":
        return _run_git(["status", "-s"], cwd) or "Working tree clean."

    elif action == "log":
        return _run_git(["log", "--oneline", "-10"], cwd)

    elif action == "diff":
        result = _run_git(["diff", "--stat"], cwd)
        return result or "No changes."

    elif action == "pull":
        return _run_git(["pull"], cwd)

    elif action == "push":
        return _run_git(["push"], cwd)

    elif action == "add_all":
        return _run_git(["add", "-A"], cwd)

    elif action == "commit":
        if not message:
            message = _generate_commit_message(cwd)
        _run_git(["add", "-A"], cwd)
        result = _run_git(["commit", "-m", message], cwd)
        return f"Committed: {message}\n{result}"

    elif action == "commit_push":
        if not message:
            message = _generate_commit_message(cwd)
        _run_git(["add", "-A"], cwd)
        commit_result = _run_git(["commit", "-m", message], cwd)
        if "nothing to commit" in commit_result.lower():
            return "Nothing to commit."
        push_result = _run_git(["push"], cwd)
        return f"Committed: {message}\nPush: {push_result}"

    elif action == "branch":
        return _run_git(["branch", "-a"], cwd)

    elif action == "checkout":
        if not branch:
            return "Please specify a branch name."
        return _run_git(["checkout", branch], cwd)

    return f"Unknown git action: {action}"


def handle_open_project(project: str) -> str:
    import subprocess
    path = _find_project_path(project)
    try:
        subprocess.Popen(f'code "{path}"', shell=True)
        return f"Opened {project} in VS Code."
    except Exception as e:
        return f"Could not open project: {e}"


def handle_explain_code(path: str, focus: str = "") -> str:
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        # Try finding it in coding root
        from pathlib import Path as P
        matches = list(P(CODING_ROOT).rglob(p.name))
        if matches:
            p = matches[0]
        else:
            return f"File not found: {path}"

    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        if len(code) > 6000:
            code = code[:6000] + "\n... (truncated)"

        focus_str = f" Focus specifically on: {focus}." if focus else ""
        return (
            f"FILE: {p.name}\n"
            f"PATH: {p}\n"
            f"SIZE: {len(code.splitlines())} lines\n\n"
            f"{code}\n\n"
            f"[Explain what this code does in plain English.{focus_str} "
            f"Note the language, main purpose, key functions, and anything notable.]"
        )
    except Exception as e:
        return f"Could not read file: {e}"


def handle_find_project_file(filename: str, project: str = "") -> str:
    from pathlib import Path
    search_root = Path(_find_project_path(project))
    matches     = []

    try:
        for p in search_root.rglob(f"*{filename}*"):
            if ".git" not in str(p) and "node_modules" not in str(p) and "__pycache__" not in str(p):
                matches.append(str(p))
            if len(matches) >= 8:
                break
    except Exception:
        pass

    if not matches:
        return f"No files matching '{filename}' found under {search_root}."

    result = f"Found {len(matches)} match(es):\n"
    result += "\n".join(matches)
    return result


# ── GitHub repo creation ──────────────────────────────────────────────────────
def handle_create_repo(name: str, description: str = "", private: bool = False) -> str:
    import urllib.request
    import urllib.error
    import json
    import subprocess
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv()

    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        return "GITHUB_TOKEN not set in .env."

    # ── 1. Get GitHub username ─────────────────────────────────────────────────
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {token}",
                "User-Agent":    "Herald/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            user_data = json.loads(resp.read())
        username = user_data["login"]
    except Exception as e:
        return f"Could not authenticate with GitHub: {e}"

    # ── 2. Create repo on GitHub ───────────────────────────────────────────────
    try:
        payload = json.dumps({
            "name":        name,
            "description": description,
            "private":     private,
            "auto_init":   False
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.github.com/user/repos",
            data    = payload,
            headers = {
                "Authorization": f"token {token}",
                "Content-Type":  "application/json",
                "User-Agent":    "Herald/1.0"
            },
            method = "POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            repo_data   = json.loads(resp.read())
            remote_url  = repo_data["clone_url"]
            repo_url    = repo_data["html_url"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if "already exists" in body:
            return f"A repo named '{name}' already exists on your GitHub."
        return f"GitHub API error: {e} — {body}"
    except Exception as e:
        return f"Could not create GitHub repo: {e}"

    # ── 3. Init locally ────────────────────────────────────────────────────────
    local_path = Path(CODING_ROOT) / name
    try:
        local_path.mkdir(parents=True, exist_ok=True)

        git_exe = _get_git_exe()
        def git(args):
            return subprocess.run(
                [git_exe] + args, cwd=str(local_path),
                capture_output=True, text=True
            )

        git(["init"])
        git(["branch", "-M", "main"])

        # Create a README
        readme = local_path / "README.md"
        readme.write_text(f"# {name}\n\n{description}\n")

        git(["add", "-A"])
        git(["commit", "-m", "chore: initial commit"])
        git(["remote", "add", "origin", remote_url])
        push = git(["push", "-u", "origin", "main"])

        if push.returncode != 0:
            return (
                f"Repo created on GitHub at {repo_url} "
                f"and initialised locally at {local_path}, "
                f"but push failed: {push.stderr.strip()}. "
                f"Try pushing manually."
            )

    except Exception as e:
        return f"GitHub repo created at {repo_url} but local setup failed: {e}"

    # ── 4. Open in VS Code ─────────────────────────────────────────────────────
    try:
        subprocess.Popen(f'code "{local_path}"', shell=True)
    except Exception:
        pass

    visibility = "private" if private else "public"
    return (
        f"Created {visibility} repo '{name}' on GitHub and locally at {local_path}. "
        f"Opened in VS Code. {repo_url}"
    )


# ── Self editing ──────────────────────────────────────────────────────────────
# Pending edit state — shared between tool and UI approval
_pending_edit = {
    "file":     None,
    "original": None,
    "proposed": None,
    "diff":     None,
}
_edit_approval_callback = None   # set by Herald after init

def set_edit_approval_callback(fn):
    global _edit_approval_callback
    _edit_approval_callback = fn

def get_pending_edit() -> dict:
    return _pending_edit.copy()

def clear_pending_edit():
    _pending_edit.update({"file": None, "original": None, "proposed": None, "diff": None})

def apply_pending_edit() -> str:
    """Apply the pending edit — write file and git commit."""
    import subprocess
    if not _pending_edit["file"] or not _pending_edit["proposed"]:
        return "No pending edit to apply."
    path = Path("C:/Coding/Herald") / _pending_edit["file"]
    try:
        # Write the new content
        with open(path, "w", encoding="utf-8") as f:
            f.write(_pending_edit["proposed"])
        # Auto git commit
        subprocess.run(
            ["git", "add", str(path)],
            cwd="C:/Coding/Herald", capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", f"chore(self-edit): {_pending_edit['file']} — AI-approved change"],
            cwd="C:/Coding/Herald", capture_output=True
        )
        fname = _pending_edit["file"]
        clear_pending_edit()
        return f"Applied and committed changes to {fname}."
    except Exception as e:
        return f"Failed to apply edit: {e}"


def handle_self_edit(file: str, instruction: str) -> str:
    import anthropic
    import difflib
    import os
    from dotenv import load_dotenv
    load_dotenv()

    herald_dir = Path("C:/Coding/Herald")
    path       = herald_dir / file

    if not path.exists():
        return f"File not found: {file}"

    # Read original
    with open(path, "r", encoding="utf-8") as f:
        original = f.read()

    # Make backup
    backup = path.with_suffix(path.suffix + ".bak")
    with open(backup, "w", encoding="utf-8") as f:
        f.write(original)

    # Ask Claude to make the change
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model      = "claude-sonnet-4-5",
        max_tokens = 4096,
        messages   = [{
            "role":    "user",
            "content": (
                f"You are editing a Python file for an AI assistant called Herald. "
                f"Here is the current content of {file}:\n\n{original}\n\n"
                f"Make this change: {instruction}\n\n"
                f"Reply with ONLY the complete updated file content. "
                f"No explanation, no markdown fences, just the raw Python code."
            )
        }]
    )
    proposed = response.content[0].text.strip()

    # Generate diff
    diff_lines = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=f"{file} (original)",
        tofile=f"{file} (proposed)",
        n=3
    ))
    diff = "".join(diff_lines[:80])   # cap at 80 lines for readability
    if len(diff_lines) > 80:
        diff += f"\n... ({len(diff_lines) - 80} more lines)"

    # Store pending edit
    _pending_edit["file"]     = file
    _pending_edit["original"] = original
    _pending_edit["proposed"] = proposed
    _pending_edit["diff"]     = diff

    # Notify UI if callback set
    if _edit_approval_callback:
        _edit_approval_callback(_pending_edit.copy())

    return (
        f"Proposed change to {file} ready for review. "
        f"Check the UI for the diff, then say 'yes apply it' or 'no discard it'."
    )


# ── Steam ─────────────────────────────────────────────────────────────────────
def _parse_vdf_value(line: str) -> str:
    """Extract the value from a VDF key/value line."""
    parts = line.strip().split("	")
    parts = [p.strip().strip('"') for p in parts if p.strip().strip('"')]
    return parts[-1] if parts else ""


def _get_steam_libraries() -> list[str]:
    """Read libraryfolders.vdf and return all Steam library paths."""
    vdf_path = r"C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf"
    libraries = [r"C:\Program Files (x86)\Steam\steamapps"]

    try:
        with open(vdf_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if '"path"' in line.lower():
                path = _parse_vdf_value(line)
                if path and os.path.isdir(path):
                    steamapps = os.path.join(path, "steamapps")
                    if os.path.isdir(steamapps) and steamapps not in libraries:
                        libraries.append(steamapps)
    except Exception:
        pass

    return libraries


def _get_installed_games() -> dict[str, str]:
    """
    Scan all Steam library folders and return a dict of
    { normalised_game_name: app_id }
    """
    games = {}
    for lib in _get_steam_libraries():
        try:
            for acf in Path(lib).glob("appmanifest_*.acf"):
                app_id = None
                name   = None
                try:
                    with open(acf, "r", encoding="utf-8") as f:
                        for line in f:
                            l = line.strip().lower()
                            if '"appid"' in l:
                                app_id = _parse_vdf_value(line)
                            if '"name"' in l:
                                name = _parse_vdf_value(line)
                            if app_id and name:
                                break
                except Exception:
                    continue
                if app_id and name:
                    games[name.lower()] = app_id
        except Exception:
            pass
    return games


def handle_steam_launch(game_name: str) -> str:
    games = _get_installed_games()

    if not games:
        return "Could not read Steam library. Make sure Steam is installed at the default path."

    query = game_name.lower().strip()

    # Exact match first
    if query in games:
        app_id = games[query]
        webbrowser.open(f"steam://rungameid/{app_id}")
        return f"Launching {game_name}."

    # Partial match
    matches = [(name, aid) for name, aid in games.items() if query in name]
    if not matches:
        # Reverse partial — query words appear in name
        words = query.split()
        matches = [(name, aid) for name, aid in games.items()
                   if all(w in name for w in words)]

    if not matches:
        installed = ", ".join(sorted(games.keys())[:10])
        return f"No game matching '{game_name}' found. Installed games include: {installed}..."

    # Pick the closest match (shortest name = most specific)
    matches.sort(key=lambda x: len(x[0]))
    name, app_id = matches[0]
    webbrowser.open(f"steam://rungameid/{app_id}")
    return f"Launching {name}."


# ── Dispatcher ─────────────────────────────────────────────────────────────────
def execute_tool(tool_name: str, tool_input: dict) -> str:
    handlers = {
        "open_application":  lambda i: handle_open_application(i["app_name"]),
        "web_search":        lambda i: handle_web_search(i["query"]),
        "open_url":          lambda i: handle_open_url(i["url"]),
        "file_search":       lambda i: handle_file_search(i["name"], i.get("search_path", "")),
        "create_folder":     lambda i: handle_create_folder(i["path"]),
        "system_control":    lambda i: handle_system_control(i["action"]),
        "get_time":          lambda i: handle_get_time(i.get("format", "both")),
        "set_timer":         lambda i: handle_set_timer(i["duration_seconds"], i.get("label", "Timer")),
        "cancel_timer":      lambda i: handle_cancel_timer(i["label"]),
        "spotify_control":   lambda i: handle_spotify_control(i["action"], i.get("query", "")),
        "daily_briefing":    lambda i: handle_daily_briefing(),
        "add_reminder":      lambda i: handle_add_reminder(i["text"], i["date"]),
        "list_reminders":    lambda i: handle_list_reminders(),
        "delete_reminder":   lambda i: handle_delete_reminder(i["query"]),
        "get_weather":       lambda i: handle_get_weather(i.get("city", "")),
        "system_monitor":    lambda i: handle_system_monitor(i.get("metric", "all")),
        "remember":          lambda i: handle_remember(i["content"]),
        "forget":            lambda i: handle_forget(i["query"]),
        "list_memories":     lambda i: handle_list_memories(),

        "run_command":       lambda i: handle_run_command(i["command"], i.get("working_dir", ""), i.get("background", False)),
        "read_file":         lambda i: handle_read_file(i["path"], i.get("max_lines", 200)),
        "write_file":        lambda i: handle_write_file(i["path"], i["content"], i.get("mode", "overwrite")),
        "clipboard":         lambda i: handle_clipboard(i["action"], i.get("content", "")),
        "create_repo":       lambda i: handle_create_repo(i["name"], i.get("description", ""), i.get("private", False)),
        "git_command":       lambda i: handle_git_command(i["action"], i.get("project", ""), i.get("message", ""), i.get("branch", "")),
        "open_project":      lambda i: handle_open_project(i["project"]),
        "explain_code":      lambda i: handle_explain_code(i["path"], i.get("focus", "")),
        "find_project_file": lambda i: handle_find_project_file(i["filename"], i.get("project", "")),
        "self_edit":         lambda i: handle_self_edit(i["file"], i["instruction"]),
        "steam_launch":      lambda i: handle_steam_launch(i["game_name"]),
        "window_management": lambda i: handle_window_management(i["action"], i.get("app_name", "")),
    }

    handler = handlers.get(tool_name)
    if not handler:
        return f"Unknown tool: {tool_name}"

    try:
        return handler(tool_input)
    except Exception as e:
        return f"Tool error: {e}"
