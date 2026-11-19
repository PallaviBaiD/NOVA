# Nova — Reading Notes

Nova is a voice-driven 3D avatar assistant. Python is the brain and voice, and a web page shows the face. It runs on your PC, and a phone can connect over Wi-Fi.

## Files
| File | Role |
|---|---|
| `nova_server.py` (~960 lines) | The whole backend: AI calls, live data, voice, routine, HTTP server |
| `nova_avatar_py.html` | The page: 3D avatar, mic recording, speech, buttons |
| `avatar` / `avatar.glb` | The 3D model file (optional; it can also be chosen in the page) |
| `routine.json` | Saved daily routine and reminders |
| `phone_key.txt`, `nova_phone_qr.png` | Phone-mode key and the QR code for the link |
| `.env` | API keys (`OPENAI_API_KEY` here; `GEMINI_API_KEY` is also supported). Keep it private |
| `*.pre-*.py/html`, `*backup*` | Old versions saved before each feature was added. Safe to ignore |

## Architecture
```
Browser page (3D face, mic, speechSynthesis)  <--HTTP-->  nova_server.py  (ThreadingHTTPServer, port 8765)
Phone browser (same Wi-Fi, QR + key + cookie)                |- brain: Gemini <-> OpenAI (fallback)
                                                             |- live data: time, weather, news, Wikipedia
                                                             |- Windows built-in voice (TTS)
                                                             |- reminder thread (routine)
                                                             |- image, slides and document generation
```
There are no pip dependencies, only the Python standard library. The browser is a display and recorder. The server decides what happens.

## Endpoints
`/chat`, `/listen` (audio), `/greet`, `/stop`, `/mute`, `/routine`, `/brain`, `/status`, `/avatar.glb`

## Pipeline for one turn
1. You speak (the browser records audio) or type.
2. `live_data()` checks whether the question needs weather, news, wiki or time, and fetches it.
3. `ask_ai()` sends the audio or text, the last 6 messages, your routine, any attachment and the live facts to the main brain. If it fails, it tries the other brain.
4. The AI returns structured JSON: transcript, reply, dance, language, routine plan, document, image prompt and slides.
5. The server acts on the JSON: it generates images or slides, updates the routine and remembers the exchange.
6. The reply is spoken (the Windows voice on the PC, or the phone's own speech) while the avatar animates and may dance.
7. With no key at all, `get_reply()` answers using simple rules.

## Run it
```powershell
python nova_server.py            # opens http://127.0.0.1:8765/
python nova_server.py --phone    # also listens on the LAN and prints a private link with ?key=...
```
- `NOVA_BRAIN=openai` or `gemini` chooses the main brain. Otherwise it picks automatically.
- Press Ctrl+C to stop.
- In phone mode, treat the printed link as a password.

## Gotchas
- The mic needs a secure context. On a phone over plain HTTP it may be unavailable, and the page says so.
- Windows may ask to allow Python on private networks. Allow it for phone mode.
- Without a `.glb` file next to the script, the page asks you to choose an avatar.
- The server reads keys from the environment, then `.env` next to the script.
- Model names are listed in `MODELS`. Update them when Google retires one.

## Compared with the ChatBot app
Nova's AI is a controller that returns commands, and the logic lives on the server. ChatBot's AI only writes text, and the logic lives in the app.
