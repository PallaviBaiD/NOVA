"""Nova Avatar, Python version.

Python is Nova's brain and voice. The 3D face is shown in your web browser.

How to run:
    1. Put these files in one folder:
         nova_server.py        (this file)
         nova_avatar_py.html   (the 3D page)
         avatar.glb            (your avatar file, optional)
    2. In the VS Code terminal:  python nova_server.py
    3. Your browser opens by itself. Press Ctrl+C in the terminal to stop.

No pip install is needed. Everything here comes with Python and Windows.
"""

import base64
import json
import os
import random
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import re
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765

# ---------- Gemini (optional: without a key Nova uses the simple rules below) ----------
def _load_key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    for path in (os.path.join(HERE, ".env"),
                 os.path.join(os.path.expanduser("~"), "CESCOM", "sakala-poc", "mitra", ".env")):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("GEMINI_API_KEY="):
                        v = line.split("=", 1)[1].strip().strip("\"'")
                        if v:
                            return v
        except OSError:
            pass
    return ""


GEMINI_KEY = _load_key()
MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
history = []   # last few exchanges, so Nova remembers the conversation

SYSTEM = (
    "You are Nova, a friendly AI companion shown as a 3D avatar. Reply in one to three short, "
    "warm, spoken-style sentences, no markdown or emojis. You may tell jokes and space facts. "
    "If the user asks you to dance, set dance true. Reply in the language the user spoke or wrote "
    "(Hindi, Telugu, Spanish, French, Japanese, any language), using that language's own script. "
    "Return JSON only: {\"transcript\": <what the user said, empty if text was given>, "
    "\"reply\": <your reply>, \"dance\": <true or false>, "
    "\"lang\": <BCP-47 code of the reply language, for example en, hi, te, es, fr>, "
    "\"plan\": <null, or the COMPLETE updated routine when the user asks you to make, change or add to a "
    "plan, routine or schedule: a list of {\"time\": \"HH:MM\" 24-hour start, \"title\": short name, "
    "\"steps\": [short steps], \"days\": \"daily\" or \"weekdays\" or \"weekend\" or a list like [\"mon\",\"wed\"], "
    "\"lang\": language code for the reminder}>}. When you return a plan, keep the reply to one short sentence "
    "saying what you saved. If a current routine is given to you, use it to answer questions about the plan."
)


def ask_gemini(text=None, audio=None, mime="audio/webm", facts=None):
    """Return (transcript, reply, dance, lang, plan) from Gemini, or None if it cannot be used."""
    if not GEMINI_KEY:
        return None
    parts = []
    for who, said in history[-6:]:
        parts.append({"text": f"{who}: {said}"})
    if audio:
        parts.append({"inline_data": {"mime_type": mime, "data": audio}})
        parts.append({"text": "The user spoke the audio above. Transcribe it and answer."})
    else:
        parts.append({"text": "User: " + text})
    if routine:
        parts.append({"text": "Current saved routine (JSON): " + json.dumps(routine, ensure_ascii=False)})
    if facts:
        parts.append({"text": "Live facts just fetched for this question (use them, put them in your own "
                              "short spoken words): " + facts})
    body = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
    }).encode("utf-8")
    for model in MODELS:
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=body, method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY})
            with urllib.request.urlopen(req, timeout=25) as r:
                out = json.loads(r.read().decode("utf-8"))
            raw = out["candidates"][0]["content"]["parts"][0]["text"]
            d = json.loads(raw)
            return (str(d.get("transcript", "")).strip(), str(d.get("reply", "")).strip(), bool(d.get("dance")),
                    str(d.get("lang", "en")).strip() or "en", d.get("plan"))
        except Exception:
            continue
    return None


# ---------- Live data (no extra keys needed) ----------
DEFAULT_CITY = os.environ.get("NOVA_CITY", "").strip()
WEATHER_WORDS = {0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy",
                 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
                 65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
                 81: "rain showers", 82: "heavy showers", 95: "a thunderstorm", 96: "a thunderstorm",
                 99: "a thunderstorm"}


def _get(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "NovaLocal/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_time():
    now = time.localtime()
    return time.strftime("It is %I:%M %p on %A, %d %B %Y.", now)


def get_weather(city):
    if not city:
        return "Which city should I check the weather for? Say: weather in, and then the city."
    geo = json.loads(_get("https://geocoding-api.open-meteo.com/v1/search?count=1&name="
                          + urllib.parse.quote(city)))
    if not geo.get("results"):
        return f"I could not find a city called {city}."
    g = geo["results"][0]
    w = json.loads(_get("https://api.open-meteo.com/v1/forecast?current=temperature_2m,weather_code,"
                        f"wind_speed_10m&latitude={g['latitude']}&longitude={g['longitude']}"))["current"]
    sky = WEATHER_WORDS.get(w.get("weather_code"), "mixed weather")
    return (f"In {g['name']} it is {round(w['temperature_2m'])} degrees Celsius with {sky}, "
            f"and wind at {round(w['wind_speed_10m'])} kilometres per hour.")


def get_news():
    root = ET.fromstring(_get("https://feeds.bbci.co.uk/news/rss.xml"))
    titles = [i.findtext("title") for i in root.iter("item")][:4]
    return "Top headlines: " + " ... ".join(t for t in titles if t)


def get_wiki(topic):
    d = json.loads(_get("https://en.wikipedia.org/api/rest_v1/page/summary/"
                        + urllib.parse.quote(topic.strip().replace(" ", "_"))))
    extract = d.get("extract", "")
    if not extract or d.get("type") == "disambiguation":
        return None
    sentences = re.split(r"(?<=[.!?])\s+", extract)
    return " ".join(sentences[:2])


def live_data(text):
    """If the question needs real-world data, fetch it and return a short fact sentence, else None."""
    t = text.lower().strip().rstrip("?.!")
    try:
        if re.search(r"\b(what('?s| is) the (time|date|day)|what time|current time|today'?s date|what day)\b", t):
            return get_time()
        if re.search(r"\b(weather|temperature|forecast)\b", t):
            m = re.search(r"\b(?:in|at|for)\s+([a-z .'-]+)$", t)
            return get_weather((m.group(1).strip() if m else DEFAULT_CITY))
        if re.search(r"\b(news|headlines)\b", t):
            return get_news()
        m = re.match(r"(?:who is|who was|what is|what are|tell me about|explain)\s+(?:a |an |the )?(.+)$", t)
        if m and not re.search(r"\b(your|my|you|me|name|joke|fact)\b", m.group(1)):
            return get_wiki(m.group(1))
    except Exception:
        return None
    return None


# ---------- Planner: Nova keeps a routine and reminds you ----------
ROUTINE_FILE = os.path.join(HERE, "routine.json")
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
notices = []            # reminders waiting for the page to pick up
notice_lock = threading.Lock()


def load_routine():
    try:
        with open(ROUTINE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


routine = load_routine()


def apply_plan(plan):
    """Validate a plan from Gemini and save it. Returns True if it was saved."""
    global routine
    if not isinstance(plan, list) or not plan:
        return False
    clean = []
    for it in plan:
        if not isinstance(it, dict):
            continue
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(it.get("time", "")))
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            continue
        days = it.get("days", "daily")
        if isinstance(days, list):
            days = [str(d).lower()[:3] for d in days if str(d).lower()[:3] in DAY_NAMES]
        elif str(days).lower() not in ("daily", "weekdays", "weekend"):
            days = "daily"
        steps = it.get("steps", [])
        clean.append({
            "time": "%02d:%02d" % (int(m.group(1)), int(m.group(2))),
            "title": str(it.get("title", "Reminder"))[:80],
            "steps": [str(x)[:120] for x in steps][:8] if isinstance(steps, list) else [],
            "days": days if days else "daily",
            "lang": str(it.get("lang", "en"))[:10] or "en",
        })
    if not clean:
        return False
    clean.sort(key=lambda x: x["time"])
    routine = clean
    try:
        with open(ROUTINE_FILE, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return True


def _runs_today(item, wd):
    d = item["days"]
    if d == "daily":
        return True
    if d == "weekdays":
        return wd < 5
    if d == "weekend":
        return wd >= 5
    return DAY_NAMES[wd] in d


def reminder_loop():
    fired = set()
    while True:
        now = time.localtime()
        hhmm = "%02d:%02d" % (now.tm_hour, now.tm_min)
        for item in list(routine):
            key = (now.tm_yday, item["time"], item["title"])
            if item["time"] == hhmm and key not in fired and _runs_today(item, now.tm_wday):
                fired.add(key)
                text = item["title"] + ". " + ". ".join(item["steps"][:5])
                browser = speak(text, item["lang"])
                with notice_lock:
                    notices.append({"reply": text, "lang": item["lang"], "browser_voice": browser})
        if len(fired) > 200:
            fired.clear()
        time.sleep(15)


def routine_text():
    if not routine:
        return "I have no plan saved yet. Say: plan my day, and tell me your timings."
    lines = []
    for it in routine:
        d = it["days"] if isinstance(it["days"], str) else ", ".join(it["days"])
        lines.append(f"{it['time']} ({d}) {it['title']}" + (": " + "; ".join(it["steps"]) if it["steps"] else ""))
    return "\n".join(lines)


def remember(user, nova):
    history.append(("User", user))
    history.append(("Nova", nova))
    del history[:-12]


# ---------- Nova's memory ----------
user_name = None
muted = False

# ---------- Nova's brain ----------
jokes = [
    "Why did the astronaut break up with the moon? He needed more space.",
    "I told the toaster a joke. It just burned out laughing.",
    "Why do robots never panic? We have nerves of steel.",
    "What do you call a sleepy robot? A snooze-bot.",
]
space_facts = [
    "A day on Venus is longer than a year on Venus.",
    "Space is completely silent because there is no air for sound to travel through.",
    "One million Earths could fit inside the Sun.",
    "Footprints on the Moon can last for millions of years because there is no wind.",
]


def get_reply(text):
    """Return (what Nova says, should Nova dance)."""
    global user_name
    t = text.lower().strip()

    found = re.search(r"(?:my name is|i am|i'm)\s+([a-z]+)", t)
    if found:
        user_name = found.group(1).capitalize()
        return f"Nice to meet you, {user_name}! Ask me for a joke or a space fact, or tell me to dance.", False
    if re.search(r"\b(bye|goodbye|quit)\b", t):
        return "Goodbye" + (f" {user_name}" if user_name else "") + "! Come back soon.", False
    if "dance" in t:
        return "Watch these moves!", True
    if "joke" in t:
        return random.choice(jokes), False
    if "fact" in t or "space" in t:
        return random.choice(space_facts), False
    if "your name" in t or "who are you" in t:
        return "I am Nova, your AI friend.", False
    if "my name" in t:
        if user_name:
            return f"Your name is {user_name}.", False
        return "I do not know yet. Say: my name is, and then your name.", False
    if "how are you" in t:
        return "I am doing great, thanks for asking!", False
    if re.search(r"\b(hi|hello|hey)\b", t):
        if user_name:
            return f"Hello again, {user_name}!", False
        return "Hello! What is your name?", False
    return "Interesting! Tell me more, or ask me for a joke, a space fact or a dance.", False


# ---------- Nova's voice (Windows built-in) ----------
speak_lock = threading.Lock()      # one voice at a time
count_lock = threading.Lock()
pending = 0                        # how many sentences are waiting or being spoken
current_proc = [None]              # the voice process that is speaking right now
stopped = threading.Event()        # set while a stop is cutting speech off


def stop_speaking():
    """Cut off the current voice (used when the user starts talking)."""
    stopped.set()
    proc = current_proc[0]
    if proc and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
    threading.Timer(0.5, stopped.clear).start()


_cultures = []


def installed_cultures():
    """Language codes of the Windows voices installed here (cached), for example ['en-US']."""
    if not _cultures:
        try:
            flags = 0x08000000 if os.name == "nt" else 0
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                 ".GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Culture.Name }"],
                capture_output=True, text=True, timeout=20, creationflags=flags).stdout
            _cultures.extend(c.strip().lower() for c in out.split() if c.strip())
        except Exception:
            pass
        if not _cultures:
            _cultures.append("en-us")
    return _cultures


def server_voice_for(lang):
    """True if Windows can speak this language here. Otherwise the browser speaks it."""
    base = (lang or "en").lower().split("-")[0]
    return base == "en" or any(c.split("-")[0] == base for c in installed_cultures())


def _speak_now(text, lang="en"):
    global pending
    with speak_lock:
        try:
            if muted:
                raise RuntimeError("muted")
            env = os.environ.copy()
            env["NOVA_TEXT"] = text
            env["NOVA_LANG"] = (lang or "en").split("-")[0]
            command = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "foreach ($v in $s.GetInstalledVoices()) { "
                "if ($v.VoiceInfo.Culture.TwoLetterISOLanguageName -eq $env:NOVA_LANG) "
                "{ $s.SelectVoice($v.VoiceInfo.Name); break } }; "
                "$s.Speak($env:NOVA_TEXT)"
            )
            flags = 0x08000000 if os.name == "nt" else 0   # hide the black console window
            proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", command],
                                    env=env, creationflags=flags)
            current_proc[0] = proc
            if proc.wait() != 0 and not stopped.is_set():
                raise RuntimeError("voice failed")
        except Exception:
            # muted, or no Windows voice here: just keep the mouth moving for a moment
            time.sleep(max(1.2, len(text) * 0.07))
    with count_lock:
        pending -= 1


def speak(text, lang="en"):
    """Speak on the PC if a voice for this language exists. Returns True if the browser must speak instead."""
    global pending
    if not server_voice_for(lang):
        return True
    with count_lock:
        pending += 1
    threading.Thread(target=_speak_now, args=(text, lang), daemon=True).start()
    return False


# ---------- The little web server ----------
def find_avatar():
    for name in ["avatar.glb"] + sorted(os.listdir(HERE)):
        path = os.path.join(HERE, name)
        if not os.path.isfile(path):
            continue
        if name.lower().endswith(".glb"):
            return path
        if name.lower() == "avatar":          # no extension: accept it if it is a real glb
            with open(path, "rb") as f:
                if f.read(4) == b"glTF":
                    return path
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the terminal quiet

    def _send(self, code, body, content_type="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            page = os.path.join(HERE, "nova_avatar_py.html")
            if not os.path.isfile(page):
                self._send(500, "nova_avatar_py.html is missing. Put it in the same folder as nova_server.py.", "text/plain")
                return
            with open(page, "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif path == "/avatar.glb":
            avatar = find_avatar()
            if avatar is None:
                self._send(404, {"error": "no avatar file"})
                return
            with open(avatar, "rb") as f:
                self._send(200, f.read(), "model/gltf-binary")
        elif path == "/routine":
            self._send(200, {"reply": routine_text(), "routine": routine})
        elif path == "/brain":
            self._send(200, {"gemini": bool(GEMINI_KEY)})
        elif path == "/status":
            with count_lock:
                speaking_now = pending > 0
            with notice_lock:
                out, notices[:] = list(notices), []
            self._send(200, {"speaking": speaking_now, "muted": muted, "notices": out})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        global muted
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}

        if path == "/chat":
            text = str(data.get("text", ""))
            facts = live_data(text)
            g = ask_gemini(text=text, facts=facts)
            lang = "en"
            if g and g[1]:
                _, reply, dance, lang, plan = g
                apply_plan(plan)
            elif facts:
                reply, dance = facts, False
            else:
                reply, dance = get_reply(text)
            remember(text, reply)
            browser = speak(reply, lang)
            self._send(200, {"reply": reply, "dance": dance, "lang": lang, "browser_voice": browser,
                             "brain": "gemini" if g else "rules"})
        elif path == "/listen":
            audio = data.get("audio_b64", "")
            g = ask_gemini(audio=audio, mime=str(data.get("mime", "audio/webm"))) if audio else None
            if not g:
                self._send(200, {"error": "I could not hear that. Check the Gemini key and try again."})
                return
            heard, reply, dance, lang, plan = g
            apply_plan(plan)
            facts = live_data(heard) if heard else None
            if facts:
                g2 = ask_gemini(text=heard, facts=facts)
                if g2 and g2[1]:
                    reply, lang = g2[1], g2[3]
                    apply_plan(g2[4])
                else:
                    reply, lang = facts, "en"
            if not heard or not reply:
                self._send(200, {"error": "I did not catch that. Please say it again."})
                return
            remember(heard, reply)
            browser = speak(reply, lang)
            self._send(200, {"heard": heard, "reply": reply, "dance": dance, "lang": lang,
                             "browser_voice": browser})
        elif path == "/greet":
            reply = "Hello! I am Nova. Ask me for a joke, a space fact, or tell me to dance."
            speak(reply, "en")
            self._send(200, {"reply": reply})
        elif path == "/stop":
            stop_speaking()
            self._send(200, {"ok": True})
        elif path == "/mute":
            muted = bool(data.get("muted"))
            self._send(200, {"muted": muted})
        else:
            self._send(404, {"error": "not found"})


def main():
    threading.Thread(target=reminder_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    avatar = find_avatar()
    print("Nova is awake at", url)
    print("Brain:", "Gemini (listens and thinks)" if GEMINI_KEY else "simple rules (no GEMINI_API_KEY found)")
    if avatar:
        print("Avatar file:", os.path.basename(avatar))
    else:
        print("No .glb avatar file found next to this script. You can choose one in the page.")
    print("Press Ctrl+C to stop.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGoodbye!")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()