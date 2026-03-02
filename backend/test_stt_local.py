"""
Local STT test: captures audio from your Mac microphone and streams it
to ElevenLabs Scribe via the official SDK.

Usage:
    python3 backend/test_stt_local.py

Speak into your mic – you should see partial and committed transcripts
printed in the terminal. Press Ctrl+C to stop.
"""

import asyncio
import base64
import os
import wave
import sys

import pyaudio
from dotenv import load_dotenv
from elevenlabs.client import AsyncElevenLabs
from elevenlabs.realtime.scribe import AudioFormat, CommitStrategy, RealtimeAudioOptions
from elevenlabs.realtime.connection import RealtimeEvents

load_dotenv()

ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
SAMPLE_RATE = 16000
CHUNK_FRAMES = 2056  # ~256 ms at 16 kHz


async def main():
    client = AsyncElevenLabs(api_key=ELEVENLABS_API_KEY)

    # Let user pass language code via CLI, e.g. python test_stt_local.py en
    language = sys.argv[1] if len(sys.argv) > 1 else "en"
    options: RealtimeAudioOptions = {
        "model_id": "scribe_v2_realtime",
        "audio_format": AudioFormat.PCM_16000,
        "sample_rate": SAMPLE_RATE,
        "commit_strategy": CommitStrategy.VAD,
        "vad_silence_threshold_secs": 1.0,
        "vad_threshold": 0.4,
        "language_code": "en",
    }

    print(f"Connecting to ElevenLabs STT (language: {language})...")
    connection = await client.speech_to_text.realtime.connect(options)

    # ---- event handlers ----
    def on_session_started(data):
        print(f"[session_started] {data}")

    def on_partial(data):
        text = data.get("text", "").strip()
        if text:
            print(f"  [partial] {text}")

    def on_committed(data):
        text = data.get("text", "").strip()
        if text:
            print(f"  ✅ [committed] {text}")

    def on_error(data):
        print(f"  ❌ [error] {data}")

    def on_close():
        print("[connection closed]")

    connection.on(RealtimeEvents.SESSION_STARTED, on_session_started)
    connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT, on_partial)
    connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT, on_committed)
    connection.on(RealtimeEvents.ERROR, on_error)
    connection.on(RealtimeEvents.CLOSE, on_close)

    # ---- open config for saving wav file ----
    wav_filename = "debug_audio_local.wav"
    wf = wave.open(wav_filename, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(pyaudio.PyAudio().get_sample_size(pyaudio.paInt16))
    wf.setframerate(SAMPLE_RATE)

    # ---- open mic ----
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_FRAMES,
    )

    print(f"🎙️  Listening on mic (rate={SAMPLE_RATE}, chunk={CHUNK_FRAMES})...")
    print(f"🖭  Saving raw recorded audio to: {os.path.abspath(wav_filename)}")
    print("   Speak into your microphone. Press Ctrl+C to stop.\n")

    try:
        while True:
            # Read PCM from mic (blocking, so run in executor)
            pcm_bytes = await asyncio.get_event_loop().run_in_executor(
                None, stream.read, CHUNK_FRAMES, False
            )
            # Write to our local WAV file
            wf.writeframes(pcm_bytes)
            
            # Send to ElevenLabs
            b64 = base64.b64encode(pcm_bytes).decode("utf-8")
            asyncio.create_task(connection.send({"audio_base_64": b64}))
    except KeyboardInterrupt:
        print("\n⏹  Stopping...")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
        wf.close()
        await connection.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
