# v2: har klipdan HARAKAT eng ko'p (eng muhim) qismlarni olib beat-sinxron montaj
import json, os, subprocess, glob
import cv2, numpy as np
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
BASE = 'C:/Users/Asilbek/OneDrive/Documents/remote'
MEDIA = BASE + '/media'
USER = sorted(glob.glob(MEDIA + '/user/*.mp4'))
TMP = BASE + '/premiere/segs3'
STEP = 4  # har necha beatda kesish (2=tez, 4=sekinroq)
OUTNAME = 'MONTAJ_v3.mp4'
os.makedirs(TMP, exist_ok=True)


def activity_profile(path, sample_fps=6, size=(160, 284)):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    dur = total / fps if total else 0
    step = max(1, int(round(fps / sample_fps)))
    prev = None
    times, acts = [], []
    idx = 0
    while True:
        if not cap.grab():
            break
        if idx % step == 0:
            ok, fr = cap.retrieve()
            if not ok:
                break
            g = cv2.cvtColor(cv2.resize(fr, size), cv2.COLOR_BGR2GRAY)
            if prev is not None:
                acts.append(float(np.mean(cv2.absdiff(g, prev))))
                times.append(idx / fps)
            prev = g
        idx += 1
    cap.release()
    return np.array(times or [0.0]), np.array(acts or [0.0]), dur


print('harakat tahlili...')
profiles = []
for p in USER:
    t, a, dur = activity_profile(p)
    profiles.append((t, a, dur))
    print(f'  {os.path.basename(p)}: {dur:.1f}s, o\'rtacha harakat={a.mean():.1f}')


def best_window(k, d, used):
    t, a, dur = profiles[k]
    if dur < d + 0.05:
        return 0.0
    best_s, best_score = 0.0, -1
    s = 0.0
    while s <= dur - d:
        # [s, s+d] oralig'idagi harakat yig'indisi
        mask = (t >= s) & (t < s + d)
        score = a[mask].sum() if mask.any() else 0
        # ishlatilgan oralig'iga yaqinlik jarima
        for (us, ue) in used:
            if not (s + d <= us or s >= ue):
                score *= 0.25
        if score > best_score:
            best_score, best_s = score, s
        s += 0.25
    used.append((best_s, best_s + d))
    return round(best_s, 3)


b = json.load(open(MEDIA + '/beats.json'))
beats = b['beats']
DUR = min(b['duration'], 37.13)
cuts = sorted(set([0.0] + beats[::STEP] + [DUR]))
cuts = [c for c in cuts if c <= DUR]

used = [[] for _ in USER]
placements = []
for j in range(len(cuts) - 1):
    s = cuts[j]
    d = round(cuts[j + 1] - cuts[j], 3)
    if d < 0.15:
        continue
    k = j % len(USER)
    ip = best_window(k, d, used[k])
    placements.append((k, ip, d))

print('segmentlar:', len(placements))
vf = 'scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,setsar=1'
listfile = TMP + '/list.txt'
with open(listfile, 'w', encoding='utf-8') as lf:
    for i, (k, ip, d) in enumerate(placements):
        out = f'{TMP}/seg_{i:03d}.mp4'
        subprocess.run([FF, '-y', '-ss', str(ip), '-i', USER[k], '-t', str(d),
                        '-vf', vf, '-an', '-c:v', 'libx264', '-preset', 'veryfast',
                        '-crf', '20', '-pix_fmt', 'yuv420p', out], capture_output=True)
        lf.write(f"file '{out}'\n")
print('birlashtirilmoqda...')
cv = TMP + '/m.mp4'
subprocess.run([FF, '-y', '-f', 'concat', '-safe', '0', '-i', listfile, '-c', 'copy', cv], capture_output=True)
final = MEDIA + '/' + OUTNAME
subprocess.run([FF, '-y', '-i', cv, '-i', MEDIA + '/reel_audio.m4a',
                '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac',
                '-b:a', '192k', '-shortest', final], capture_output=True)
print(f'TAYYOR: {final} ({os.path.getsize(final)/1024/1024:.1f} MB)')
