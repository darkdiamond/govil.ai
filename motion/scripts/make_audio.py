#!/usr/bin/env python3
"""Hebrew voiceover + quiet music + minimal SFX, muxed onto the silent render.

  python3 scripts/make_audio.py all | <scene>  [--no-voice]

Inputs : data/events/<scene>.json (cue timeline: node events.mjs), out/silent/<scene>.mp4,
         scripts/narration.py (what the narrator says, anchored to segment starts)
Outputs: out/audio/<scene>.wav, out/<scene>.mp4 (video copied, AAC, ~-14 LUFS)
Voice  : Microsoft Edge neural TTS via `edge-tts` (needs internet; clips are cached in data/tts/).
         VOICE env var picks the voice: he-IL-HilaNeural (default, female) | he-IL-AvriNeural (male)."""
import asyncio, hashlib, json, os, pathlib, subprocess, sys, wave
import numpy as np
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root / 'scripts'))
SR = 44100
VOICE = os.environ.get('VOICE', 'he-IL-HilaNeural'); RATE = os.environ.get('TTS_RATE', '+4%')
MAX_TEMPO = 1.28
MODES = {'minor': [[0, 3, 7], [8, 0, 3], [3, 7, 10], [10, 2, 5]], 'major': [[0, 4, 7], [7, 11, 2], [9, 0, 4], [5, 9, 0]]}
SECTOR_MAJOR = {'10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '01', '05', '06'}
mf = lambda m: 440.0 * 2 ** ((m - 69) / 12)

# ---------- synthesis helpers
def env_exp(n, tau): return np.exp(-np.arange(n) / SR / tau)
def put(buf, x, t, g=1.0):
    i = int(t * SR)
    if i >= len(buf) or i < 0: return
    j = min(len(buf), i + len(x)); buf[i:j] += x[:j - i] * g
def sine(f, d, tau=None):
    n = int(d * SR); x = np.sin(2 * np.pi * f * np.arange(n) / SR)
    return x * (env_exp(n, tau) if tau else np.hanning(n))
def lowpass(x, k): k = max(1, int(k)); return np.convolve(x, np.ones(k) / k, mode='same')
def pluck(f, d):
    n = int(d * SR); t = np.arange(n) / SR; x = sum(np.sin(2 * np.pi * f * h * t) / h * np.exp(-t * (4 + 5 * h)) for h in range(1, 5))
    return x * np.minimum(1, t * 300)

def music(D, seed, key, mode, bpm):
    """Calm bed: slow pad, soft bass on 1 & 3, gentle quarter-note arp. No drums."""
    n = int(D * SR); L = np.zeros(n); R = np.zeros(n); beat = 60 / bpm; bar = beat * 4; chords = MODES[mode]
    for b in range(int(D / bar) + 2):
        ch = chords[b % 4]; third = 4 if (mode == 'major' or b % 4) else 3
        notes = [key + ch[0] + iv for iv in (0, third, 7)]
        for m in notes:
            for k, det in enumerate((-0.1, 0.1)):
                d = bar + .8; nn = int(d * SR); x = sine(mf(m + 12) * 2 ** (det / 12), d) * np.minimum(1, np.arange(nn) / SR / .9)
                put(L if k == 0 else R, x, b * bar, .05); put(R if k == 0 else L, x, b * bar, .025)
        r = key + ch[0] - 12
        for step in (0, 2):
            x = sine(mf(r), beat * 1.6, tau=.5); put(L, x, b * bar + step * beat, .22); put(R, x, b * bar + step * beat, .22)
        for s in range(4):
            t = b * bar + s * beat
            if t < 1.2: continue
            m = notes[[0, 2, 1, 2][s]] + 12 * (1 + (s == 3)); x = pluck(mf(m), beat * 1.8); pan = .3 + .4 * (s % 2)
            put(L, x, t, .06 * (1 - pan)); put(R, x, t, .06 * pan)
    f = np.minimum(1, np.arange(n) / SR / 1.2) * np.minimum(1, (D - np.arange(n) / SR) / 1.8)
    return np.stack([L * f, R * f])

def sfx(events, D, key, mode):
    """Only: a soft swish on scene changes and a sparkle on confetti. Everything else is the narrator."""
    rs = np.random.default_rng(5); n = int(D * SR); L = np.zeros(n); R = np.zeros(n); pent = [0, 2, 4, 7, 9] if mode == 'major' else [0, 3, 5, 7, 10]
    for e in events:
        k, t = e['k'], e['t']
        if k == 'seg' and t > 0.1:
            d = .45; w = lowpass(rs.standard_normal(int(d * SR)), 24) * np.hanning(int(d * SR)) * 7
            put(L, w, max(0, t - .12), .05); put(R, w, max(0, t - .12), .05)
        elif k == 'confetti':
            for i in range(5):
                x = sine(mf(key + 72 + pent[rs.integers(0, 5)]), .5, tau=.12); put(L, x, t + i * .07, .05); put(R, x, t + i * .07, .05)
    return np.stack([L, R])

# ---------- voiceover
def tts_clip(text):
    import edge_tts
    h = hashlib.sha1(f'{VOICE}|{RATE}|{text}'.encode()).hexdigest()[:16]; p = root / f'data/tts/{h}.mp3'
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(edge_tts.Communicate(text, VOICE, rate=RATE).save(str(p)))
    return p
def decode(p, tempo=1.0):
    af = f'atempo={tempo:.4f},' if tempo > 1.001 else ''
    r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', str(p), '-af', af + 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse', '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-'], capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype='<f4').copy()

def voice(scene, ev, D):
    from narration import SCRIPTS
    segs = sorted(e['t'] for e in ev['events'] if e['k'] == 'seg'); lines = SCRIPTS[scene]
    anchors = [segs[s] + o for s, o, _ in lines]; v = np.zeros(int(D * SR)); warn = []; prev_end = 0.0
    for i, ((s, o, text), a0) in enumerate(zip(lines, anchors)):
        t0 = max(a0, prev_end + .14)  # never overlap the previous line; push back instead
        nxt = (anchors[i + 1] - .14) if i + 1 < len(anchors) else D - .5
        x = decode(tts_clip(text)); dur = len(x) / SR; slot = nxt - t0
        if dur > slot and slot > 0.3:  # speed up, but only as far as MAX_TEMPO
            x = decode(tts_clip(text), min(MAX_TEMPO, dur / slot)); dur = len(x) / SR
        x = x * np.minimum(1, np.arange(len(x)) / SR / .02)
        put(v, x, t0); prev_end = t0 + dur
        if t0 - a0 > .9 or prev_end > D - .3: warn.append(f'  DRIFT line {i}: starts {t0 - a0:+.1f}s late, ends {prev_end:.1f}/{D}s: {text[:36]}')
    return v, warn

def duck_env(v, depth=.35):
    a = np.abs(v); win = int(.12 * SR); e = np.convolve(a, np.ones(win) / win, mode='same'); on = (e > .01).astype(float)
    sm = np.convolve(on, np.hanning(int(.35 * SR)) / np.hanning(int(.35 * SR)).sum(), mode='same')
    return 1 - (1 - depth) * np.clip(sm, 0, 1)

# ---------- mix + mux
def sh(cmd, **k): return subprocess.run(cmd, capture_output=True, text=True, **k)
def build(scene, with_voice=True):
    ev = json.load(open(root / f'data/events/{scene}.json')); D = ev['duration']; num = scene[:2]; seed = int(num)
    key = [57, 55, 52, 60, 53, 57, 59, 62, 55, 57, 60, 53, 55, 57, 52, 60, 55, 53, 57, 59][(seed - 1) % 20]
    mode = 'major' if num in SECTOR_MAJOR else 'minor'; bpm = 84 + (seed * 5) % 17
    m = music(D, seed, key, mode, bpm); s = sfx(ev['events'], D, key, mode)
    if with_voice:
        v, warn = voice(scene, ev, D); [print(w) for w in warn]
        m = m * duck_env(v)[None, :]; vox = np.stack([v, v]) * 1.0
    else: vox = 0
    mix = m * .62 + s + vox
    mix = np.tanh(mix * 1.1) / 1.1
    mix = mix / max(1e-6, np.abs(mix).max()) * .85
    (root / 'out/audio').mkdir(parents=True, exist_ok=True); wav = root / f'out/audio/{scene}.wav'
    def write(path, x):
        with wave.open(str(path), 'wb') as w: w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(x, -1, 1).T * 32767).astype('<i2').tobytes())
    write(wav, mix)
    # two-pass linear loudnorm (single constant gain), then a hard safety ceiling before AAC
    ln = 'loudnorm=I=-14:TP=-2:LRA=11'
    r = sh(['ffmpeg', '-hide_banner', '-i', str(wav), '-af', ln + ':print_format=json', '-f', 'null', '-'])
    j = json.loads(r.stderr[r.stderr.rindex('{'):])
    ln += f":measured_I={j['input_i']}:measured_LRA={j['input_lra']}:measured_TP={j['input_tp']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true"
    tmp = root / f'out/audio/{scene}.norm.wav'
    sh(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(wav), '-af', ln, '-ar', str(SR), '-c:a', 'pcm_f32le', str(tmp)], check=True)
    x = np.frombuffer(subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', str(tmp), '-f', 'f32le', '-ac', '2', '-ar', str(SR), '-'], capture_output=True, check=True).stdout, dtype='<f4').reshape(-1, 2).T
    x = x * min(1, .72 / max(1e-6, np.abs(x).max()))  # ≈ -3 dBFS ceiling leaves room for AAC overshoot
    write(tmp, x)
    src = root / f'out/silent/{scene}.mp4'; out = root / f'out/{scene}.mp4'
    sh(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(src), '-i', str(tmp), '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-af', f'afade=t=out:st={D - 0.9:.2f}:d=0.9',
        '-c:a', 'aac', '-b:a', '192k', '-ar', str(SR), '-shortest', '-movflags', '+faststart', str(out)], check=True)
    tmp.unlink(); print('audio', scene, f'{bpm}bpm {mode}', 'voice' if with_voice else 'music-only')

if __name__ == '__main__':
    a = sys.argv[1]; nv = '--no-voice' in sys.argv
    for sc in (sorted(p.stem for p in (root / 'data/events').glob('[0-9]*.json')) if a == 'all' else [a]): build(sc, not nv)
