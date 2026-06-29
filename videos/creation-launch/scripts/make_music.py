"""Deterministic upbeat electro-pop bed for the Creation launch video.

124 BPM, bright I-V-vi-IV progression, four-on-the-floor groove with claps,
plucky bass, detuned saw chord-stabs and a peppy 16th arpeggio. Pure numpy ->
16-bit WAV. No external models or keys.
"""
import math
import struct
import wave

import numpy as np

SR = 44100
BPM = 124.0
BEAT = 60.0 / BPM           # 0.4839 s
BAR = BEAT * 4
BARS = 18                   # ~34.8 s of groove
TAIL = 1.4                  # decay after last bar
DUR = BARS * BAR + TAIL
N = int(DUR * SR)
t = np.arange(N) / SR

rng = np.random.default_rng(7)  # deterministic noise

# ---- helpers ---------------------------------------------------------------
def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12.0)

def env(length, a=0.005, d=0.0, s=1.0, r=0.05, sus_level=0.7):
    """Simple ADSR over `length` seconds, returned as a sample array."""
    ln = int(length * SR)
    e = np.zeros(ln)
    ai = max(1, int(a * SR)); di = int(d * SR); ri = max(1, int(r * SR))
    e[:ai] = np.linspace(0, 1, ai)
    if di > 0:
        e[ai:ai + di] = np.linspace(1, sus_level, di)
        si = ai + di
    else:
        si = ai
    rs = max(si, ln - ri)
    e[si:rs] = sus_level if di > 0 else 1.0
    e[rs:] = np.linspace(e[rs - 1] if rs > 0 else 1.0, 0, ln - rs)
    return e

def add(buf, sig, start_s):
    i = int(start_s * SR)
    j = min(len(buf), i + len(sig))
    if i >= len(buf):
        return
    buf[i:j] += sig[: j - i]

def saw(freq, length, detune=0.0):
    ln = int(length * SR)
    tt = np.arange(ln) / SR
    f = freq * (1 + detune)
    # band-limited-ish saw via summed harmonics (cheap, warm)
    out = np.zeros(ln)
    for h in range(1, 12):
        out += ((-1) ** (h + 1)) / h * np.sin(2 * math.pi * f * h * tt)
    return out / np.max(np.abs(out) + 1e-9)

def square(freq, length):
    ln = int(length * SR)
    tt = np.arange(ln) / SR
    return np.sign(np.sin(2 * math.pi * freq * tt))

def sine(freq, length):
    ln = int(length * SR)
    tt = np.arange(ln) / SR
    return np.sin(2 * math.pi * freq * tt)

# ---- drum voices -----------------------------------------------------------
def kick():
    ln = int(0.32 * SR)
    tt = np.arange(ln) / SR
    pitch = 150 * np.exp(-tt * 32) + 48
    body = np.sin(2 * math.pi * np.cumsum(pitch) / SR)
    click = np.exp(-tt * 220) * 0.6
    return (body * np.exp(-tt * 7) + click) * 0.95

def clap():
    ln = int(0.22 * SR)
    tt = np.arange(ln) / SR
    noise = rng.standard_normal(ln)
    e = np.exp(-tt * 22) + 0.5 * np.exp(-((tt - 0.012) ** 2) / 2e-5)
    band = noise * e
    return band * 0.5

def hat(open_=False):
    ln = int((0.12 if open_ else 0.05) * SR)
    tt = np.arange(ln) / SR
    noise = rng.standard_normal(ln)
    e = np.exp(-tt * (28 if open_ else 70))
    return noise * e * 0.28

# ---- arrangement -----------------------------------------------------------
buf = np.zeros(N)

# Chord roots (MIDI) for I-V-vi-IV in C: C(60) G(67) Am(57) F(53), bright voicings
prog = [
    (60, [60, 64, 67, 72]),   # C
    (67, [59, 62, 67, 71]),   # G
    (57, [57, 60, 64, 69]),   # Am
    (53, [60, 65, 69, 72]),   # F
]

def bar_chord(b):
    return prog[b % 4]

for b in range(BARS):
    bar_t = b * BAR
    root, chord = bar_chord(b)
    full = b >= 2                 # groove enters bar 3
    bright = b >= 9               # second-half lift

    # kick four-on-the-floor (from bar 2)
    if b >= 1:
        for beat in range(4):
            add(buf, kick(), bar_t + beat * BEAT)
    # clap on 2 & 4
    if full:
        add(buf, clap(), bar_t + BEAT)
        add(buf, clap(), bar_t + 3 * BEAT)
    # hats on 8ths, open on the 'and'
    if full:
        for k in range(8):
            add(buf, hat(open_=(k % 2 == 1)), bar_t + k * (BEAT / 2))

    # bass: plucky root/fifth eighth bounce
    if full:
        bpat = [root, root, root + 7, root, root, root + 7, root, root + 12]
        for k, nt in enumerate(bpat):
            seg = saw(midi(nt - 12), 0.22, detune=0.002) * env(0.22, a=0.004, r=0.06)
            add(buf, seg * 0.5, bar_t + k * (BEAT / 2))

    # chord stabs: detuned saws on beats 1 & 3 (off-accent on 'and of 2' for bounce)
    if full:
        for beat_pos in (0.0, 1.5, 2.0, 3.5):
            stab = np.zeros(int(0.42 * SR))
            for nt in chord:
                s = (saw(midi(nt), 0.42, detune=0.004) + saw(midi(nt), 0.42, detune=-0.004))
                stab += s[: len(stab)]
            stab *= env(0.42, a=0.006, d=0.10, sus_level=0.0, r=0.18) * 0.12
            add(buf, stab, bar_t + beat_pos * BEAT)

    # arp: peppy 16th-note chord tones
    arp_notes = chord + [chord[1] + 12]
    oct_up = 12 if bright else 0
    for k in range(16):
        nt = arp_notes[k % len(arp_notes)] + oct_up
        seg = (square(midi(nt), 0.14) * 0.5 + sine(midi(nt), 0.14) * 0.5)
        seg *= env(0.14, a=0.003, r=0.05) * 0.16
        # intro bars: only arp, softer
        gain = 0.7 if not full else 1.0
        add(buf, seg * gain, bar_t + k * (BEAT / 4))

# Riser into the hero reveal (~bar 4 downbeat = 5.806s) and into CTA
def riser(end_s, length=1.6):
    ln = int(length * SR)
    tt = np.arange(ln) / SR
    f = np.linspace(200, 2200, ln)
    sweep = np.sin(2 * math.pi * np.cumsum(f) / SR)
    noise = rng.standard_normal(ln) * 0.3
    e = (tt / length) ** 2
    sig = (sweep * 0.4 + noise) * e * 0.4
    add(buf, sig, end_s - length)

riser(3 * BAR)          # into hero reveal
riser(14 * BAR)         # into CTA

# Final impact on the last CTA downbeat
add(buf, kick() * 1.2, 14 * BAR)
crash_ln = int(1.6 * SR)
crash = rng.standard_normal(crash_ln) * np.exp(-np.arange(crash_ln) / SR * 4) * 0.35
add(buf, crash, 14 * BAR)

# ---- master --------------------------------------------------------------
buf = np.tanh(buf * 1.1)                 # soft saturation glue
buf *= 0.92 / (np.max(np.abs(buf)) + 1e-9)
# fades
fi = int(0.06 * SR)
buf[:fi] *= np.linspace(0, 1, fi)
fo = int(1.3 * SR)
buf[-fo:] *= np.linspace(1, 0, fo)

pcm = (buf * 32767).astype(np.int16)
with wave.open("assets/music.wav", "w") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())

print(f"wrote assets/music.wav  dur={DUR:.2f}s  bars={BARS}  bpm={BPM}")
