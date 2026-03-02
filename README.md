<p align="center">
  <h1 align="center">🎙️ YANKI — Voice-Controlled Web Browser Agent</h1>
  <p align="center">
    <em>Talk to the web. Literally.</em>
  </p>
  <p align="center">
    <strong>Mistral AI Hackathon Project</strong>
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Mistral_Large-Tool_Calling-orange?style=for-the-badge" alt="Mistral Large"/>
  <img src="https://img.shields.io/badge/ElevenLabs-STT_%2B_TTS-blue?style=for-the-badge" alt="ElevenLabs"/>
  <img src="https://img.shields.io/badge/Playwright-Browser_Automation-green?style=for-the-badge" alt="Playwright"/>
  <img src="https://img.shields.io/badge/Python-Async-yellow?style=for-the-badge" alt="Python"/>
</p>

---

## 🚀 What is YANKI?

**YANKI** is a real-time, bidirectional voice agent that lets you **browse the web entirely with your voice**. Just speak naturally — YANKI listens, understands your intent, navigates websites, fills forms, clicks buttons, and reads results back to you out loud.

No typing. No clicking. Just talk.

**Example interactions:**

> 🗣️ *"Go to Amazon and search for wireless headphones under fifty dollars"*
>
> 🗣️ *"Open YouTube and play lo-fi hip hop"*
>
> 🗣️ *"Go to Google Flights, find me a round trip from Istanbul to San Francisco next month"*

YANKI handles **multi-step tasks autonomously** — it doesn't stop after one action. It keeps navigating, clicking, typing, and scrolling until your entire request is fulfilled, narrating each step along the way. Just open the microphone by saying *"just start"* and begin talking.

---

## 🏗️ Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                        YANKI CLI                             │
│                                                              │
│  ┌──────────┐    ┌──────────┐    ┌───────────────────────┐  │
│  │ 🎤 PyAudio│───▶│ ElevenLabs│───▶│   Mistral Large LLM   │  │
│  │   (Mic)   │    │   STT    │    │   (Tool-calling Agent)│  │
│  └──────────┘    └──────────┘    └───────────┬───────────┘  │
│                                               │              │
│                                    ┌──────────▼──────────┐  │
│  ┌──────────┐    ┌──────────┐    │  🌐 Playwright       │  │
│  │ 🔊 PyAudio│◀───│ ElevenLabs│◀───│  Browser Controller  │  │
│  │ (Speaker) │    │   TTS    │    │  + DOM Extractor     │  │
│  └──────────┘    └──────────┘    └───────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **🎤 Mic Capture** — PyAudio captures your microphone audio in real-time (PCM 16kHz)
2. **🗣️ Speech-to-Text** — Audio streams to ElevenLabs Scribe via WebSocket for low-latency transcription
3. **🧠 LLM Reasoning** — Committed transcripts are sent to Mistral Large, which reasons about the request and decides which browser tools to call
4. **🌐 Browser Actions** — Playwright executes the tool calls (click, type, scroll, navigate, etc.) on a live Chromium browser
5. **📖 Page Understanding** — After each action, a custom DOM extractor injects into the page, identifies all visible interactive elements, and sends a structured text snapshot back to the LLM
6. **🔁 Agentic Loop** — The LLM plans the next step based on updated page state — this continues for up to 10 iterations until the task is complete
7. **🔊 Text-to-Speech** — The LLM's verbal responses stream through ElevenLabs TTS and play through your speakers in real-time

---

## ✨ Key Features

| Feature | Description |
|---|---|
| **🗣️ Full Voice Control** | Speak naturally — no wake words needed once activated. Say *"just start"* to open the mic, *"just stop"* to sleep. |
| **🤖 Autonomous Multi-Step Agent** | Give complex instructions and YANKI completes them end-to-end across multiple page navigations. |
| **🌐 Real Browser Automation** | Uses a visible Chromium browser via Playwright — watch it navigate in real-time as you speak. |
| **⚡ Real-Time Interruption** | Start speaking at any time to interrupt the agent mid-action. TTS stops immediately and the agent listens. |
| **🧩 Smart DOM Extraction** | Custom JS extractor identifies all interactive elements on screen, assigns IDs, and creates a compact text representation for the LLM. |
| **🖼️ Iframe Support** | Can read and interact with elements inside iframes (embedded content, payment forms, etc.). |
| **📜 Conversation Memory** | Maintains conversation history (capped at 30 messages) with intelligent truncation to avoid orphaned tool calls. |
| **🎯 Action History** | The LLM tracks its recent actions to avoid loops and maintain context across navigation steps. |
| **📝 Comprehensive Logging** | Every session is logged to `logs/` with full debug output, plus raw audio WAV capture for debugging. |

---

## 🛠️ Tech Stack

| Component | Technology | Role |
|---|---|---|
| **LLM** | [Mistral Large](https://mistral.ai/) (`mistral-large-latest`) | Reasoning engine with native tool/function calling |
| **Speech-to-Text** | [ElevenLabs Scribe](https://elevenlabs.io/) (real-time WebSocket) | Low-latency streaming transcription with VAD |
| **Text-to-Speech** | [ElevenLabs](https://elevenlabs.io/) (`eleven_flash_v2_5`) | Natural streaming voice synthesis (PCM 24kHz) |
| **Browser Automation** | [Playwright](https://playwright.dev/) (Chromium) | Headful browser control with full DOM access |
| **Audio I/O** | [PyAudio](https://people.csail.mit.edu/hubert/pyaudio/) | Local microphone capture & speaker playback |
| **Async Runtime** | Python `asyncio` | Non-blocking I/O for all concurrent operations |

---

## 📦 Installation

### Prerequisites

- **Python 3.9+**
- A working **microphone** and **speakers**
- API keys for **Mistral AI** and **ElevenLabs**

### 1. Clone the repository

```bash
git clone https://github.com/your-username/yanki.git
cd yanki
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright browsers

```bash
python -m playwright install chromium
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
MISTRAL_API_KEY=your_mistral_api_key_here
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here

# Optional: customize the TTS voice (defaults to a built-in voice)
# ELEVENLABS_VOICE_ID=your_preferred_voice_id
```

---

## ▶️ Usage

### Start YANKI

```bash
python run.py
```

This will:
1. Launch a visible Chromium browser window
2. Connect to ElevenLabs STT/TTS services
3. Open your microphone and speakers
4. Start listening for your commands

### Voice Commands

| Command | Action |
|---|---|
| **"just start"** | Wake up the agent — opens the microphone and starts listening for instructions |
| **"just stop"** | Put the agent to sleep — stops processing commands |
| **Ctrl+C** | Quit the application |

### Example Session

```
============================================================
  🎙️  YANKI CLI – Voice Web Navigator
  Say 'just start' to wake, 'just stop' to sleep
  Press Ctrl+C to quit
============================================================

  ✅ You said: just start
  🟢 AWAKE — listening for commands

  ✅ You said: go to wikipedia and search for artificial intelligence

  🤖 YANKI: "Navigating to Wikipedia now."
  [Browser navigates to wikipedia.org]
  🤖 YANKI: "Searching for artificial intelligence."
  [Browser types in search bar and submits]
  🤖 YANKI: "Here's the Wikipedia article on Artificial Intelligence."
```

---

## 🧰 Available Browser Tools

The LLM agent has access to the following tools for web interaction:

| Tool | Description |
|---|---|
| `click_element(element_id)` | Click any interactive element on the page |
| `type_text(element_id, text)` | Instantly fill text into form fields |
| `type_and_submit(element_id, text)` | Type character-by-character + press Enter (for search bars with autocomplete) |
| `select_option(element_id, value)` | Pick from dropdown menus |
| `scroll_down(amount)` / `scroll_up(amount)` | Scroll the page (intensity 1–5) |
| `go_to_url(url)` | Navigate to any URL |
| `get_iframe_content(iframe_id)` | Read elements inside embedded iframes |
| `click_iframe_element(iframe_id, element_id)` | Click inside an iframe |
| `type_iframe_text(iframe_id, element_id, text)` | Type inside an iframe |
| `answer_to_user(text)` | Speak a response out loud via TTS |

---

## 📁 Project Structure

```
yanki/
├── run.py                      # Entry point — CLI mode launcher
├── requirements.txt            # Python dependencies
├── .env                        # API keys (not committed)
├── CLAUDE.md                   # Development notes
│
├── backend/
│   ├── cli_session.py          # 🎯 Main orchestrator — mic → STT → LLM → browser → TTS
│   ├── llm_client.py           # 🧠 Mistral chat.complete wrapper + conversation history
│   ├── browser_agent.py        # 🌐 Playwright controller + DOM extraction
│   ├── dom_extractor.js        # 📖 Injected JS — maps interactive elements to [id] labels
│   ├── tools.py                # 🔧 Tool/function definitions (JSON schemas for Mistral)
│   ├── stt_client.py           # 🗣️ ElevenLabs Scribe real-time STT WebSocket
│   ├── tts_client.py           # 🔊 ElevenLabs streaming TTS client
│   ├── config.py               # ⚙️ Constants + environment variable loading
│   ├── audio_utils.py          # 🎵 PCM audio encoding utilities
│   ├── main.py                 # 🌐 FastAPI WebSocket server (alternative mode, WIP)
│   └── session.py              # 🌐 WebSocket session manager (alternative mode, WIP)
│
└── logs/                       # Session logs + debug audio recordings
    └── session_YYYYMMDD_HHMMSS.log
```

---

## 🔧 How It Works — Deep Dive

### DOM Element Addressing

YANKI uses a novel approach to let the LLM "see" and interact with web pages:

1. A custom JavaScript extractor (`dom_extractor.js`) is injected into every page
2. It walks the DOM tree and finds all **visible, interactive elements** (buttons, links, inputs, dropdowns, etc.)
3. Each element gets a sequential `data-agent-id` attribute: `[1]`, `[2]`, `[3]`, ...
4. The extractor produces a compact text representation:
   ```
   [1] "Search Wikipedia" (search input)
   [2] "English" (link)
   [3] "Log in" (link)
   [42] "Search" (button)
   ```
5. The LLM reads this list and refers to elements by their numeric ID when calling tools
6. IDs are **re-assigned on every page evaluation** to stay in sync with the live DOM

### Agentic Tool Loop

```
User speaks → STT transcript → LLM receives transcript + page state
                                          │
                                          ▼
                                ┌─── LLM decides ───┐
                                │                    │
                          Tool call(s)        answer_to_user only
                                │                    │
                                ▼                    ▼
                        Execute browser         Speak response
                        action (max 1)          → Loop exits
                                │
                                ▼
                        Re-extract DOM
                        → Feed back to LLM
                        → Next iteration
                        (max 10 iterations)
```

**Rules:**
- Only **one browser action** per LLM turn (element IDs change after actions)
- `answer_to_user` can **co-occur** with a browser action (runs concurrently)
- `answer_to_user` **alone** = final answer = loop exits
- Maximum **10 iterations** per user request

### Real-Time Interruption

When the user starts speaking while the agent is active:
1. Partial STT transcript is detected immediately
2. Current TTS playback **stops instantly**
3. The in-progress tool loop task is **cancelled**
4. `LLMClient.rollback_after_interrupt()` cleans up incomplete tool call/result pairs from conversation history
5. The new user utterance is processed fresh

This creates a natural conversational flow where you can redirect the agent at any time.

---

## ⚙️ Configuration

All configuration lives in `backend/config.py`:

| Variable | Default | Description |
|---|---|---|
| `MISTRAL_MODEL` | `mistral-large-latest` | Mistral model for reasoning |
| `WAKE_PHRASE_START` | `"just start"` | Phrase to activate the agent |
| `WAKE_PHRASE_STOP` | `"just stop"` | Phrase to deactivate the agent |
| `PCM_SAMPLE_RATE` | `16000` | Microphone capture sample rate (Hz) |
| `TTS_SAMPLE_RATE` | `24000` | TTS playback sample rate (Hz) |
| `MAX_TOOL_ITERATIONS` | `10` | Max agent loop iterations per request |
| `MAX_CONVERSATION_MESSAGES` | `30` | Conversation history cap |

---

## 🤝 Team

Built with ❤️ at the **Mistral AI Hackathon**.

---

## 📄 License

This project was built during a hackathon. See repository for license details.
