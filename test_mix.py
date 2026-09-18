import sys, os, wave, struct, math

os.makedirs("C:/Users/Bahram/podcast-bot-check/assets/intro_music", exist_ok=True)

with wave.open("C:/Users/Bahram/podcast-bot-check/output_test_speech.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
    frames = b"".join(struct.pack("<h", int(3000*math.sin(440*i/24000*2*math.pi))) for i in range(48000))
    w.writeframes(frames)

with wave.open("C:/Users/Bahram/podcast-bot-check/output_test_music.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
    frames = b"".join(struct.pack("<h", int(1500*math.sin(220*i/24000*2*math.pi))) for i in range(72000))
    w.writeframes(frames)

os.chdir("C:/Users/Bahram/podcast-bot-check")
import importlib.util
spec = importlib.util.spec_from_file_location("main", "C:/Users/Bahram/podcast-bot-check/main.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ok = m.mix_audio_with_music(
    "C:/Users/Bahram/podcast-bot-check/output_test_speech.wav",
    "C:/Users/Bahram/podcast-bot-check/output_test_out.wav",
    "C:/Users/Bahram/podcast-bot-check/output_test_music.wav",
)
assert ok, "mix failed"

out = m.AudioSegment.from_wav("C:/Users/Bahram/podcast-bot-check/output_test_out.wav")
dur = len(out) / 1000
print(f"Output duration: {dur:.2f}s (expect ~5s)")
assert 4.5 <= dur <= 5.5, f"unexpected duration {dur}"
print("MIX TEST PASSED")
