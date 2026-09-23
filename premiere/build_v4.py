# v4: qo'lda tanlangan eng yaxshi qismlar + slow-motion (dive/suv) + speed-up (sokin kadrlar)
import os, subprocess, glob, json
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
BASE = 'C:/Users/Asilbek/OneDrive/Documents/remote'
MEDIA = BASE + '/media'
USER = sorted(glob.glob(MEDIA + '/user/*.mp4'))  # 0..6 => 01..07
TMP = BASE + '/premiere/segs4'
os.makedirs(TMP, exist_ok=True)
LEN = [34.9, 4.2, 18.9, 4.5, 4.5, 3.4, 31.9]

# (fayl# 1-7, src_in, out_dur (timeline), speed: <1 sekin, >1 tez)
shots = [
    (5, 1.0, 3.0, 0.6),   # suv panorama - sekin ochilish
    (3, 3.0, 2.6, 1.0),   # hero portret
    (1, 8.0, 1.6, 2.0),   # o'tirgan - tez
    (4, 1.0, 2.0, 0.7),   # prep - biroz sekin
    (2, 0.4, 3.2, 0.5),   # DIVE - sekin
    (7, 7.5, 3.6, 0.55),  # DOLPHIN KICK - sekin kульминация!
    (7, 11.5, 2.4, 0.7),  # dolphin kick davomi
    (3, 9.0, 2.2, 1.0),   # portret yana
    (6, 0.3, 2.4, 0.6),   # suv b-roll sekin
    (7, 9.5, 2.2, 0.6),   # dolphin kick yana (sekin)
    (1, 20.0, 1.6, 2.0),  # o'tirgan tez
    (5, 0.5, 2.4, 0.6),   # suv sekin
    (2, 1.2, 1.8, 0.7),   # dive qism
    (3, 5.0, 2.8, 0.8),   # portret yakuniy sekin
]

# beat chegaralariga moslash
b = json.load(open(MEDIA + '/beats.json'))
beats = b['beats']
DUR = min(b['duration'], 37.13)


def snap(t):
    return min(beats, key=lambda x: abs(x - t)) if beats else t


# kumulyativ chegaralar -> beatga snap
outs = [s[2] for s in shots]
bounds = [0.0]
for d in outs:
    bounds.append(bounds[-1] + d)
# oxirini DURga keltiramiz
scale = DUR / bounds[-1]
bounds = [x * scale for x in bounds]
for i in range(1, len(bounds) - 1):
    bounds[i] = snap(bounds[i])
bounds[-1] = DUR

vf_base = 'scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280'
listfile = TMP + '/list.txt'
with open(listfile, 'w', encoding='utf-8') as lf:
    for i, (fno, src_in, _od, speed) in enumerate(shots):
        out_dur = round(bounds[i + 1] - bounds[i], 3)
        if out_dur < 0.2:
            continue
        src_dur = round(out_dur * speed, 3)
        k = fno - 1
        if src_in + src_dur > LEN[k] - 0.05:
            src_in = max(0.0, LEN[k] - src_dur - 0.05)
        setpts = round(1.0 / speed, 4)
        vf = f'{vf_base},setpts={setpts}*PTS,fps=30,setsar=1'
        out = f'{TMP}/seg_{i:03d}.mp4'
        subprocess.run([FF, '-y', '-ss', str(src_in), '-i', USER[k], '-t', str(src_dur),
                        '-vf', vf, '-an', '-c:v', 'libx264', '-preset', 'veryfast',
                        '-crf', '20', '-pix_fmt', 'yuv420p', out], capture_output=True)
        lf.write(f"file '{out}'\n")
        tag = 'SLOW' if speed < 1 else ('FAST' if speed > 1 else 'norm')
        print(f'  {i+1:2d}. klip{fno} in={src_in:.1f} out={out_dur:.2f}s {tag}({speed}x)')

cv = TMP + '/m.mp4'
subprocess.run([FF, '-y', '-f', 'concat', '-safe', '0', '-i', listfile, '-c', 'copy', cv], capture_output=True)
final = MEDIA + '/MONTAJ_v4.mp4'
subprocess.run([FF, '-y', '-i', cv, '-i', MEDIA + '/reel_audio.m4a',
                '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac',
                '-b:a', '192k', '-shortest', final], capture_output=True)
print(f'TAYYOR: {final} ({os.path.getsize(final)/1024/1024:.1f} MB)')
