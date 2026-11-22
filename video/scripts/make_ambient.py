"""Generate a quiet, paper-like ambient loop for the promo.

No external dependencies. The result is a mono 22.05 kHz 16-bit WAV.
"""

import math
import random
import struct
import wave
from pathlib import Path

SR = 22050
DURATION = 56.0
N = int(SR * DURATION)
rng = random.Random(11)

# A minor-ish, low and unresolved; slow breathing chords, no sharp attacks.
chords = [
    [110.00, 164.81, 220.00, 261.63],  # A2 E3 A3 C4
    [98.00, 146.83, 196.00, 246.94],  # G2 D3 G3 B3
    [87.31, 130.81, 174.61, 220.00],  # F2 C3 F3 A3
    [110.00, 164.81, 220.00, 329.63],  # A2 E3 A3 E4
]
chord_len = DURATION / len(chords)


def smoothstep(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


samples = []
for i in range(N):
    t = i / SR
    idx = min(len(chords) - 1, int(t / chord_len))
    local = (t - idx * chord_len) / chord_len
    chord = chords[idx]
    env = 0.55 + 0.45 * math.sin(math.pi * local)
    value = 0.0
    for j, f in enumerate(chord):
        detune = 1.0 + (j - 1.5) * 0.0009
        value += math.sin(2.0 * math.pi * f * detune * t + j * 0.7) / (j + 2)
    value += 0.025 * math.sin(2.0 * math.pi * 880.0 * t + 0.3)
    value += 0.012 * math.sin(2.0 * math.pi * 1318.5 * t + 1.1)
    value *= env / 2.1
    value += rng.uniform(-1.0, 1.0) * 0.0018
    fade = min(smoothstep(t / 3.0), smoothstep((DURATION - t) / 3.0))
    samples.append(int(max(-1.0, min(1.0, value * fade)) * 12000))

out = Path(__file__).resolve().parents[1] / 'public' / 'audio' / 'ambient.wav'
out.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(out), 'w') as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(SR)
    f.writeframes(b''.join(struct.pack('<h', s) for s in samples))
print(out, out.stat().st_size)
