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
import hmac
import json
import os
import random
import secrets
import socket
import sys
import urllib.error
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
    "warm, spoken-style sentences, no markdown or emojis. Reply in the language the user spoke or wrote "
    "(Hindi, Telugu, Spanish, French, Japanese, any language), using that language's own script. "
    "Return JSON only: {\"transcript\": <what the user said, empty if text was given>, "
    "\"reply\": <your reply>, "
    "\"lang\": <BCP-47 code of the reply language, for example en, hi, te, es, fr>, "
    "\"document\": <the full written text, or an empty string>, "
    "\"image\": <null, or an image to create, see IMAGES below>, "
    "\"plan\": <null, or the COMPLETE updated routine when the user asks you to make, change or add to a "
    "plan, routine or schedule: a list of {\"time\": \"HH:MM\" 24-hour start, \"title\": short name, "
    "\"steps\": [short steps], \"days\": \"daily\" or \"weekdays\" or \"weekend\" or a list like [\"mon\",\"wed\"], "
    "\"lang\": language code for the reminder}>}. When you return a plan, keep the reply to one short sentence "
    "saying what you saved. If a current routine is given to you, use it to answer questions about the plan. "
    "WRITTEN DOCUMENTS: when the user asks you to write a letter, email, leave request, message, note, "
    "application or any other text meant to be copied, put the complete text in \"document\" (plain text, "
    "normal line breaks, a greeting and a sign-off, no markdown symbols, and use [Your Name] only if the name "
    "is unknown) and keep \"reply\" to ONE short spoken sentence such as: I have written it, it is on the screen. "
    "NEVER put the letter or email text inside \"reply\"; it must go in \"document\" so it is shown on screen, not read aloud. "
    "Example: user asks for a sick leave email -> reply: \"I have written your leave email, it is on the screen.\", "
    "document: \"Dear Sir,\n\nI am not feeling well ... \n\nRegards,\n[Your Name]\". "
    "REPORTS: when the user asks for a report, summary document, analysis or notes (for example from an attached "
    "file), put it in \"document\" using \"# Title\" for the title, \"## Heading\" for sections and \"- \" for bullet "
    "points, starting with a short summary and ending with a conclusion; use only facts and numbers from the file "
    "or the conversation. Letters and emails use no # or - markers. "
    "For ordinary chat, \"document\" is an empty string. "
    "IMAGES: when the user asks you to create, draw, make or show the flag of a country, return \"image\": "
    "{\"type\": \"flag\", \"code\": <lowercase ISO 3166-1 alpha-2 country code, for example in, us, jp>, "
    "\"name\": <country name>}. When the user asks you to create, draw, paint, generate or show any other "
    "picture, photo, artwork, illustration, character, scene or made-up design, return {\"type\": \"generate\", "
    "\"name\": <short title>, \"prompt\": <a detailed English description of the image to create: subject, "
    "style, colours, lighting, background>}. Only when the user asks for an SVG, a vector, an icon or a simple "
    "diagram, return {\"type\": \"svg\", \"name\": <short title>, \"svg\": <one complete self-contained SVG "
    "string starting with <svg and a viewBox, no scripts, no external links or images>}. "
    "Keep \"reply\" to one short sentence such as: Here is your picture. Otherwise \"image\" is null. "
    "ATTACHMENTS: when the user attaches an image or a file, look at it or read it and answer about it. "
    "Keep \"reply\" to one to three spoken sentences and put any longer summary or extracted text in \"document\"."
)


# ---------- Images Nova creates (flags and simple SVG pictures) ----------
IMAGE_MODELS = [m for m in [os.environ.get("NOVA_IMAGE_MODEL", "").strip(), "gemini-2.5-flash-image",
                            "gemini-3.1-flash-image"] if m]
OPENAI_IMAGE_MODEL = os.environ.get("NOVA_OPENAI_IMAGE", "gpt-image-1").strip()


image_problem = [""]      # why the last picture could not be made, in words the user can act on


def generate_picture(prompt):
    """Create a new picture from a text description. Returns (mime, base64) or None."""
    image_problem[0] = ""
    prompt = str(prompt or "").strip()[:1500]
    if not prompt:
        return None
    if GEMINI_KEY:
        body = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                           "generationConfig": {"responseModalities": ["IMAGE"]}}).encode("utf-8")
        for model in IMAGE_MODELS:
            try:
                req = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    data=body, method="POST",
                    headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY})
                with urllib.request.urlopen(req, timeout=90) as r:
                    out = json.loads(r.read().decode("utf-8"))
                for part in out["candidates"][0]["content"]["parts"]:
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and inline.get("data"):
                        return (inline.get("mimeType") or inline.get("mime_type") or "image/png"), inline["data"]
            except urllib.error.HTTPError as e:
                if e.code in (429, 403):
                    image_problem[0] = ("Your Gemini key has no quota for making pictures. Turn on billing for it in "
                                        "Google AI Studio, or add an OpenAI key.")
                continue
            except Exception:
                continue
    if OPENAI_KEY:
        try:
            body = json.dumps({"model": OPENAI_IMAGE_MODEL, "prompt": prompt, "size": "1024x1024"}).encode("utf-8")
            req = urllib.request.Request("https://api.openai.com/v1/images/generations", data=body, method="POST",
                                         headers={"Authorization": "Bearer " + OPENAI_KEY,
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.loads(r.read().decode("utf-8"))
            b64 = out["data"][0].get("b64_json")
            if b64:
                image_problem[0] = ""
                return "image/png", b64
        except urllib.error.HTTPError as e:
            image_problem[0] = ("Your OpenAI account has no credits left. Add credits in OpenAI billing to use it."
                                if e.code == 429 else
                                "OpenAI could not make the picture (error %d). Check your billing and image access." % e.code)
        except Exception:
            pass
    # free fallback, no key needed (set NOVA_FREE_IMAGES=0 to turn it off)
    if os.environ.get("NOVA_FREE_IMAGES", "1").strip() != "0":
        try:
            url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:800])
                   + "?width=1024&height=1024&nologo=true&model=flux&seed=" + str(random.randint(1, 999999)))
            data = _get(url, timeout=90)
            if len(data) <= 2000:
                image_problem[0] = "The free picture service is busy. Please ask again in a moment."
            if len(data) > 2000:
                image_problem[0] = ""
                return ("image/png" if data[1:4] == b"PNG" else "image/jpeg"), base64.b64encode(data).decode()
        except urllib.error.HTTPError as e:
            if e.code in (402, 429):
                image_problem[0] = ("The free picture service allows one picture every 45 seconds. "
                                    "Please ask again in a moment.")
        except Exception:
            pass
    if not image_problem[0]:
        image_problem[0] = "I could not create that picture. Please try again."
    return None


def make_image(spec):
    """Turn the AI's image request into {'name','mime','b64'/'svg', 'svg'} for the page, or None."""
    if not isinstance(spec, dict):
        return None
    kind = str(spec.get("type", "")).lower()
    name = str(spec.get("name", "image"))[:60] or "image"
    if kind == "flag":
        code = str(spec.get("code", "")).lower().strip()
        if not re.match(r"^[a-z]{2}(-[a-z]{2,3})?$", code):
            return None
        try:
            png = _get("https://flagcdn.com/w1280/" + code + ".png", timeout=10)
            try:
                svg = _get("https://flagcdn.com/" + code + ".svg", timeout=10).decode("utf-8")
            except Exception:
                svg = ""
            return {"name": name, "kind": "flag", "mime": "image/png", "b64": base64.b64encode(png).decode(), "svg": svg}
        except Exception:
            return None
    if kind == "generate":
        got = generate_picture(spec.get("prompt"))
        if not got:
            return None
        return {"name": name, "kind": "generated", "mime": got[0], "b64": got[1], "svg": ""}
    if kind == "svg":
        svg = str(spec.get("svg", "")).strip()
        bad = re.search(r"<script|<foreignObject|<image|<iframe|javascript:|\bon\w+\s*=|(?:href|src)\s*=\s*[\"']?\s*(?:https?:|//|data:)",
                        svg, re.I)
        if not svg.lower().startswith("<svg") or len(svg) > 200000 or bad:
            return None
        return {"name": name, "kind": "svg", "mime": "image/svg+xml", "b64": "", "svg": svg}
    return None


# ---------- Attachments (images and files the user adds in the page) ----------
MAX_ATTACH = 8 * 1024 * 1024          # bytes after decoding
TEXT_EXT = (".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".html", ".css", ".xml", ".yml", ".yaml",
            ".ini", ".sql", ".tsv")
INLINE_MIME = ("image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf")


def prepare_attachment(a):
    """Turn what the page sent into {'name', 'mime', 'b64', 'text'}; return (attachment or None, error or '')."""
    if not a:
        return None, ""
    try:
        name = str(a.get("name", "file"))[:120]
        mime = str(a.get("mime", "")).lower().split(";")[0] or "application/octet-stream"
        b64 = str(a.get("b64", ""))
        raw = base64.b64decode(b64, validate=False)
    except Exception:
        return None, "I could not read that file."
    if len(raw) > MAX_ATTACH:
        return None, "That file is too big. Please use one under 8 megabytes."
    if mime in INLINE_MIME:
        return {"name": name, "mime": mime, "b64": b64, "text": ""}, ""
    if mime.startswith("text/") or name.lower().endswith(TEXT_EXT) or mime in ("application/json", "application/xml"):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")
        return {"name": name, "mime": "text/plain", "b64": "", "text": text[:60000]}, ""
    return None, ("I can read images, PDFs and text files such as txt, csv, json and code. "
                  "For Word or Excel files, please save them as PDF or CSV first.")


def ask_gemini(text=None, audio=None, mime="audio/webm", facts=None, attach=None):
    """Return (transcript, reply, dance, lang, plan, document, image) from Gemini, or None if it cannot be used."""
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
    if attach:
        if attach["b64"]:
            parts.append({"inline_data": {"mime_type": attach["mime"], "data": attach["b64"]}})
            parts.append({"text": f"The user attached the file named {attach['name']} above. Use it to answer."})
        else:
            parts.append({"text": f"The user attached a file named {attach['name']}. Its content:\n{attach['text']}"})
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
            return (str(d.get("transcript", "")).strip(), str(d.get("reply", "")).strip(), False,
                    str(d.get("lang", "en")).strip() or "en", d.get("plan"),
                    str(d.get("document") or "").strip(), d.get("image"))
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
        if m and not re.search(r"\b(your|my|you|me|name)\b", m.group(1)):
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


# ---------- OpenAI (optional: set OPENAI_API_KEY; NOVA_BRAIN=openai or gemini chooses the main brain) ----------
def _load_openai_key():
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"].strip()
    try:
        with open(os.path.join(HERE, ".env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("OPENAI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return ""


OPENAI_KEY = _load_openai_key()
# Model names change often. Override with NOVA_OPENAI_MODEL / NOVA_OPENAI_STT if these are out of date.
OPENAI_MODELS = [m for m in [os.environ.get("NOVA_OPENAI_MODEL", "").strip(), "gpt-4o-mini", "gpt-4o"] if m]
OPENAI_STT = os.environ.get("NOVA_OPENAI_STT", "whisper-1").strip()
BRAIN = os.environ.get("NOVA_BRAIN", "").strip().lower()    # "openai", "gemini", or empty = auto


def _openai_transcribe(audio_b64, mime):
    """Speech to text with OpenAI. Returns the text, or '' on failure."""
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3",
           "audio/wav": "wav", "audio/x-wav": "wav"}.get(mime, "webm")
    boundary = "----novaform" + str(int(time.time() * 1000))
    parts = [("model", OPENAI_STT)]
    body = b""
    for name, val in parts:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.{ext}\"\r\n"
             f"Content-Type: {mime}\r\n\r\n").encode() + base64.b64decode(audio_b64) + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request("https://api.openai.com/v1/audio/transcriptions", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + OPENAI_KEY,
                                          "Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return str(json.loads(r.read().decode("utf-8")).get("text", "")).strip()
    except Exception:
        return ""


def ask_openai(text=None, audio=None, mime="audio/webm", facts=None, attach=None):
    """Same result as ask_gemini: (transcript, reply, dance, lang, plan, document, image), or None."""
    if not OPENAI_KEY:
        return None
    transcript = ""
    if audio:
        transcript = _openai_transcribe(audio, mime)
        if not transcript:
            return None
        text = transcript
    msgs = [{"role": "system", "content": SYSTEM}]
    for who, said in history[-6:]:
        msgs.append({"role": "user" if who == "User" else "assistant", "content": said})
    extra = ""
    if routine:
        extra += "\nCurrent saved routine (JSON): " + json.dumps(routine, ensure_ascii=False)
    if facts:
        extra += "\nLive facts just fetched (use them in your own short spoken words): " + facts
    content = "User: " + text + extra + "\nAnswer with the JSON object only."
    if attach and not attach["b64"]:
        content = f"User: {text}\nAttached file {attach['name']}:\n{attach['text']}{extra}\nAnswer with the JSON object only."
    if attach and attach["b64"] and attach["mime"].startswith("image/"):
        content = [{"type": "text", "text": content},
                   {"type": "image_url", "image_url": {"url": f"data:{attach['mime']};base64,{attach['b64']}"}}]
    elif attach and attach["b64"]:
        content += f"\n(The file {attach['name']} was attached, but this model cannot open that type of file.)"
    msgs.append({"role": "user", "content": content})
    for model in OPENAI_MODELS:
        try:
            body = json.dumps({"model": model, "messages": msgs,
                               "response_format": {"type": "json_object"}, "temperature": 0.8}).encode("utf-8")
            req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body, method="POST",
                                         headers={"Authorization": "Bearer " + OPENAI_KEY,
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.loads(r.read().decode("utf-8"))
            d = json.loads(out["choices"][0]["message"]["content"])
            return (transcript or str(d.get("transcript", "")).strip(), str(d.get("reply", "")).strip(),
                    False, str(d.get("lang", "en")).strip() or "en", d.get("plan"),
                    str(d.get("document") or "").strip(), d.get("image"))
        except Exception:
            continue
    return None


def brain_order():
    avail = {"openai": bool(OPENAI_KEY), "gemini": bool(GEMINI_KEY)}
    first = BRAIN if BRAIN in avail else ("openai" if OPENAI_KEY and not GEMINI_KEY else "gemini")
    return [b for b in [first] + [x for x in avail if x != first] if avail[b]]


def ask_ai(text=None, audio=None, mime="audio/webm", facts=None, attach=None):
    """Try the main brain, then the other one if it fails."""
    for b in brain_order():
        fn = ask_openai if b == "openai" else ask_gemini
        r = fn(text=text, audio=audio, mime=mime, facts=facts, attach=attach)
        if r:
            return r
    return None


def remember(user, nova):
    history.append(("User", user))
    history.append(("Nova", nova))
    del history[:-12]


# ---------- Nova's memory ----------
user_name = None
muted = False

# ---------- Nova's brain ----------

def get_reply(text):
    """Return (what Nova says, should Nova dance)."""
    global user_name
    t = text.lower().strip()

    found = re.search(r"(?:my name is|i am|i'm)\s+([a-z]+)", t)
    if found:
        user_name = found.group(1).capitalize()
        return f"Nice to meet you, {user_name}! How can I help you?", False
    if re.search(r"\b(bye|goodbye|quit)\b", t):
        return "Goodbye" + (f" {user_name}" if user_name else "") + "! Come back soon.", False
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
    return "Interesting! Tell me more.", False


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


last_greet = [0.0]        # when Nova last said her greeting


# ---------- Phone mode: python nova_server.py --phone ----------
# Lets a phone on the same Wi-Fi open Nova. Phones must use a secret key from the link, and Nova speaks on the phone.
PHONE = ("--phone" in sys.argv) or os.environ.get("NOVA_PHONE", "").strip() == "1"
KEY_FILE = os.path.join(HERE, "phone_key.txt")


def _load_phone_key():
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            k = f.read().strip()
            if len(k) >= 6:
                return k
    except OSError:
        pass
    k = secrets.token_hex(4)
    try:
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            f.write(k)
    except OSError:
        pass
    return k


PHONE_KEY = _load_phone_key() if PHONE else ""


def lan_address():
    """This PC's address on the local network, for example 192.168.1.20."""
    try:
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.connect(("10.255.255.255", 1))        # no data is sent; this only picks the right network card
        ip = sk.getsockname()[0]
        sk.close()
        return ip
    except Exception:
        return "127.0.0.1"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the terminal quiet

    def _remote(self):
        """True when the request comes from another device (a phone), not from this PC."""
        return self.client_address[0] not in ("127.0.0.1", "::1")

    def _authorized(self):
        if not self._remote():
            return True
        if not PHONE:
            return False
        cookies = [c.strip() for c in self.headers.get("Cookie", "").split(";")]
        for c in cookies:
            if c.startswith("nova=") and hmac.compare_digest(c[5:], PHONE_KEY):
                return True
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return hmac.compare_digest(q.get("key", [""])[0], PHONE_KEY)

    def _deliver(self, reply, lang):
        """Speak on the PC, or tell a phone to speak it. Returns True when the page must speak."""
        if self._remote():
            return True
        return speak(reply, lang)

    def _send(self, code, body, content_type="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if not self._authorized():
            self._send(403, "Open the link with the key that Nova printed on the PC.", "text/plain")
            return
        if path in ("/", "/index.html"):
            page = os.path.join(HERE, "nova_avatar_py.html")
            if not os.path.isfile(page):
                self._send(500, "nova_avatar_py.html is missing. Put it in the same folder as nova_server.py.", "text/plain")
                return
            with open(page, "rb") as f:
                extra = None
                if self._remote():            # remember the key so the page can call the server
                    extra = {"Set-Cookie": "nova=" + PHONE_KEY + "; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000"}
                self._send(200, f.read(), "text/html; charset=utf-8", extra)
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
            self._send(200, {"gemini": bool(GEMINI_KEY), "openai": bool(OPENAI_KEY), "order": brain_order()})
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
        if not self._authorized():
            self._send(403, {"error": "not allowed"})
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = {}

        if path == "/chat":
            text = str(data.get("text", ""))
            attach, problem = prepare_attachment(data.get("attachment"))
            if problem:
                self._send(200, {"reply": problem, "lang": "en", "browser_voice": speak(problem, "en")})
                return
            if attach and not text.strip():
                text = "Please look at this and tell me what it is."
            facts = live_data(text) if not attach else None
            g = ask_ai(text=text, facts=facts, attach=attach)
            lang = "en"
            doc = ""
            image = None
            if g and g[1]:
                _, reply, dance, lang, plan, doc, image = g
                apply_plan(plan)
            elif facts:
                reply, dance = facts, False
            else:
                reply, dance = get_reply(text)
            picture = make_image(image)
            if isinstance(image, dict) and not picture and str(image.get("type", "")) == "generate":
                reply = image_problem[0] or reply
            remember(text + (f" [attached {attach['name']}]" if attach else ""), reply)
            browser = self._deliver(reply, lang)
            self._send(200, {"reply": reply, "dance": dance, "lang": lang, "browser_voice": browser,
                             "document": doc, "image": picture, "brain": "ai" if g else "rules"})
        elif path == "/listen":
            audio = data.get("audio_b64", "")
            g = ask_ai(audio=audio, mime=str(data.get("mime", "audio/webm"))) if audio else None
            if not g:
                self._send(200, {"error": "I could not hear that. Check the Gemini key and try again."})
                return
            heard, reply, dance, lang, plan, doc, image = g
            apply_plan(plan)
            facts = live_data(heard) if heard else None
            if facts:
                g2 = ask_ai(text=heard, facts=facts)
                if g2 and g2[1]:
                    reply, lang, doc, image = g2[1], g2[3], g2[5], g2[6]
                    apply_plan(g2[4])
                else:
                    reply, lang = facts, "en"
            if not heard or not reply:
                self._send(200, {"error": "I did not catch that. Please say it again."})
                return
            picture = make_image(image)
            if isinstance(image, dict) and not picture and str(image.get("type", "")) == "generate":
                reply = image_problem[0] or reply
            remember(heard, reply)
            browser = self._deliver(reply, lang)
            self._send(200, {"heard": heard, "reply": reply, "dance": dance, "lang": lang,
                             "browser_voice": browser, "document": doc, "image": picture})
        elif path == "/greet":
            reply = "Hello! I am Nova. How can I help you today?"
            now = time.time()
            browser = False
            if self._remote():
                browser = True                    # the phone speaks its own greeting
            elif now - last_greet[0] > 60:        # a second page opening right after the first stays quiet
                speak(reply, "en")
            if not self._remote():
                last_greet[0] = now
            self._send(200, {"reply": reply, "lang": "en", "browser_voice": browser})
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
    server = ThreadingHTTPServer(("0.0.0.0" if PHONE else "127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    avatar = find_avatar()
    print("Nova is awake at", url)
    order = brain_order()
    print("Brain:", " then ".join(order) if order else "simple rules (no GEMINI_API_KEY or OPENAI_API_KEY found)")
    if avatar:
        print("Avatar file:", os.path.basename(avatar))
    else:
        print("No .glb avatar file found next to this script. You can choose one in the page.")
    if PHONE:
        print()
        print("PHONE MODE is on. On a phone connected to the same Wi-Fi, open:")
        print(f"    http://{lan_address()}:{PORT}/?key={PHONE_KEY}")
        print("Keep that link private: it is the password. Windows may ask to allow Python on private networks: allow it.")
        print()
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