# v6: HARAKATLAR TO'LIQ (dive boshdan splashgacha, dolphin kick to'liq) + blur fon + silliq slow
import os, subprocess, glob, json
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
BASE = 'C:/Users/Asilbek/OneDrive/Documents/remote'
MEDIA = BASE + '/media'
USER = sorted(glob.glob(MEDIA + '/user/*.mp4'))
TMP = BASE + '/premiere/segs6'
os.makedirs(TMP, exist_ok=True)
LEN = [34.9, 4.2, 18.9, 4.5, 4.5, 3.4, 31.9]
ORIENT = ['port', 'land', 'port', 'land', 'port', 'port', 'land']

# (fayl#, src_in, src_out, speed, action?) — action segmentlar to'liq harakat, kesilmaydi
shots = [
    (5, 0.5, 2.3, 0.65, False),   # panorama ochilish
    (3, 3.5, 5.7, 1.0, False),    # hero portret
    (4, 0.75, 3.45, 0.45, True),  # DIVE#2 TO'LIQ (sakrash->arc->splash) silliq slow
    (7, 7.2, 11.4, 0.55, True),   # DOLPHIN KICK to'liq (bir necha zarba)
    (3, 8.5, 10.5, 1.0, False),   # portret
    (6, 0.3, 2.2, 0.65, False),   # panorama o'tish
    (2, 0.3, 2.3, 0.6, True),     # DIVE#1 TO'LIQ (sakrash->splash)
    (7, 11.6, 14.2, 0.6, True),   # dolphin kick yana
    (5, 0.4, 2.2, 0.65, False),   # panorama
    (3, 5.0, 8.2, 0.85, False),   # portret yakuniy
]

b = json.load(open(MEDIA + '/beats.json'))
AUDIO = min(b['duration'], 37.13)
DUR = AUDIO + 1.5  # video ovozdan uzunroq -> -shortest ovozni to'liq (37.13s) qoldiradi

# out_dur hisobi: action fixed, non-action DURga to'ldirish uchun skalalanadi
base = []
for (fno, si, so, sp, act) in shots:
    base.append((so - si) / sp)
act_total = sum(base[i] for i in range(len(shots)) if shots[i][4])
non_total = sum(base[i] for i in range(len(shots)) if not shots[i][4])
scale_non = (DUR - act_total) / non_total if non_total else 1.0

listfile = TMP + '/list.txt'
with open(listfile, 'w', encoding='utf-8') as lf:
    for i, (fno, si, so, sp, act) in enumerate(shots):
        k = fno - 1
        out_dur = base[i] if act else base[i] * scale_non
        src_dur = round(out_dur * sp, 3)
        src_in = si
        if src_in + src_dur > LEN[k] - 0.03:
            src_dur = LEN[k] - src_in - 0.03
            out_dur = src_dur / sp
        setpts = round(1.0 / sp, 4)
        pre = ''
        if fno in (1, 2, 3) and sp < 1.0:
            pre = 'minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc,'
        if ORIENT[k] == 'land':
            fc = (f'[0:v]{pre}split[a][b];'
                  f'[a]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,gblur=sigma=22[bg];'
                  f'[b]scale=720:-2[fg];'
                  f'[bg][fg]overlay=(W-w)/2:(H-h)/2,setpts={setpts}*PTS,fps=30,setsar=1[v]')
        else:
            fc = (f'[0:v]{pre}scale=720:1280:force_original_aspect_ratio=increase,'
                  f'crop=720:1280,setpts={setpts}*PTS,fps=30,setsar=1[v]')
        out = f'{TMP}/seg_{i:03d}.mp4'
        # -ss va -t INPUT oldiga: manbadan aynan src_dur o'qiladi, slow-mo kesilmaydi
        subprocess.run([FF, '-y', '-ss', str(src_in), '-t', str(round(src_dur, 3)), '-i', USER[k],
                        '-filter_complex', fc, '-map', '[v]', '-an',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                        '-pix_fmt', 'yuv420p', out], capture_output=True)
        lf.write(f"file '{out}'\n")
        tag = 'ACTION' if act else 'broll'
        print(f'  {i+1:2d}. klip{fno}({ORIENT[k]}) src={si:.1f}-{si+src_dur:.1f} out={out_dur:.2f}s {tag} {"SLOW" if sp<1 else ("FAST" if sp>1 else "")}')

cv = TMP + '/m.mp4'
subprocess.run([FF, '-y', '-f', 'concat', '-safe', '0', '-i', listfile, '-c', 'copy', cv], capture_output=True)
final = MEDIA + '/MONTAJ_v6.mp4'
subprocess.run([FF, '-y', '-i', cv, '-i', MEDIA + '/reel_audio.m4a',
                '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac',
                '-b:a', '192k', '-shortest', final], capture_output=True)
print(f'TAYYOR: {final} ({os.path.getsize(final)/1024/1024:.1f} MB)')
