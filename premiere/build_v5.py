# v5: blur-fon (gorizontal kliplar to'liq), silliq slow-mo (minterpolate), hikoyaviy struktura
import os, subprocess, glob, json
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
BASE = 'C:/Users/Asilbek/OneDrive/Documents/remote'
MEDIA = BASE + '/media'
USER = sorted(glob.glob(MEDIA + '/user/*.mp4'))
TMP = BASE + '/premiere/segs5'
os.makedirs(TMP, exist_ok=True)
LEN = [34.9, 4.2, 18.9, 4.5, 4.5, 3.4, 31.9]
ORIENT = ['port', 'land', 'port', 'land', 'port', 'port', 'land']  # 1..7

# hikoyaviy struktura: (fayl#, src_in, out_dur, speed)
shots = [
    (5, 0.8, 3.0, 0.6),   # havza panorama - sokin ochilish
    (3, 4.0, 2.5, 1.0),   # hero portret - suzuvchini tanishtirish
    (1, 8.0, 1.5, 1.8),   # o'tirgan/prep - qisqa, tez (kutish)
    (4, 0.9, 3.0, 0.5),   # DIVE#2 (chiroyli arc, 60fps) - silliq slow
    (7, 7.3, 5.0, 0.5),   # DOLPHIN KICK - uzun silliq KULMINATSIYA
    (3, 9.0, 2.2, 1.0),   # portret
    (6, 0.3, 2.5, 0.6),   # panorama - silliq o'tish
    (2, 0.4, 2.5, 0.6),   # DIVE#1 splash (30fps -> interpolate)
    (7, 11.5, 3.2, 0.55), # dolphin kick yana
    (5, 0.5, 2.2, 0.6),   # panorama slow
    (3, 5.5, 3.2, 0.85),  # portret - yakuniy slow
]

b = json.load(open(MEDIA + '/beats.json'))
beats = b['beats']
DUR = min(b['duration'], 37.13)


def snap(t):
    return min(beats, key=lambda x: abs(x - t)) if beats else t


bounds = [0.0]
for s in shots:
    bounds.append(bounds[-1] + s[2])
sc = DUR / bounds[-1]
bounds = [x * sc for x in bounds]
for i in range(1, len(bounds) - 1):
    bounds[i] = snap(bounds[i])
bounds[-1] = DUR

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
        sp = round(1.0 / speed, 4)  # setpts koeffitsiyenti
        pre = ''
        # 30fps kliplarni (1,2,3) sekinlashtirganda silliq qilamiz
        if fno in (1, 2, 3) and speed < 1.0:
            pre = 'minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc,'
        if ORIENT[k] == 'land':
            fc = (f'[0:v]{pre}split[a][b];'
                  f'[a]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,gblur=sigma=22[bg];'
                  f'[b]scale=720:-2[fg];'
                  f'[bg][fg]overlay=(W-w)/2:(H-h)/2,setpts={sp}*PTS,fps=30,setsar=1[v]')
        else:
            fc = (f'[0:v]{pre}scale=720:1280:force_original_aspect_ratio=increase,'
                  f'crop=720:1280,setpts={sp}*PTS,fps=30,setsar=1[v]')
        out = f'{TMP}/seg_{i:03d}.mp4'
        subprocess.run([FF, '-y', '-ss', str(src_in), '-i', USER[k], '-t', str(src_dur),
                        '-filter_complex', fc, '-map', '[v]', '-an',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                        '-pix_fmt', 'yuv420p', out], capture_output=True)
        lf.write(f"file '{out}'\n")
        tag = 'SLOW' if speed < 1 else ('FAST' if speed > 1 else 'norm')
        print(f'  {i+1:2d}. klip{fno}({ORIENT[k]}) in={src_in:.1f} out={out_dur:.2f}s {tag}')

cv = TMP + '/m.mp4'
subprocess.run([FF, '-y', '-f', 'concat', '-safe', '0', '-i', listfile, '-c', 'copy', cv], capture_output=True)
final = MEDIA + '/MONTAJ_v5.mp4'
subprocess.run([FF, '-y', '-i', cv, '-i', MEDIA + '/reel_audio.m4a',
                '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac',
                '-b:a', '192k', '-shortest', final], capture_output=True)
print(f'TAYYOR: {final} ({os.path.getsize(final)/1024/1024:.1f} MB)')
