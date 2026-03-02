import os
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

MISTRAL_API_KEY = os.environ["MISTRAL_API_KEY"]
MISTRAL_MODEL = "mistral-large-latest"

WAKE_PHRASE_START = "just start"
WAKE_PHRASE_STOP = "just stop"

PCM_SAMPLE_RATE = 16000
TTS_SAMPLE_RATE = 24000

MAX_TOOL_ITERATIONS = 10
MAX_CONVERSATION_MESSAGES = 30
