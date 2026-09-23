# Beat-sinxron montajni ffmpeg bilan yig'adi (720x1280 vertikal, scale-to-fill) + reel ovozi
import json, os, subprocess, glob
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
BASE = 'C:/Users/Asilbek/OneDrive/Documents/remote'
MEDIA = BASE + '/media'
USER = sorted(glob.glob(MEDIA + '/user/*.mp4'))  # 01..07
TMP = BASE + '/premiere/segs'
os.makedirs(TMP, exist_ok=True)

b = json.load(open(MEDIA + '/beats.json'))
beats = b['beats']
DUR = min(b['duration'], 37.13)
cuts = sorted(set([0.0] + beats[::2] + [DUR]))
cuts = [c for c in cuts if c <= DUR]

# klip davomiyliklari (soniya)
durs = [34.9, 4.2, 18.9, 4.5, 4.5, 3.4, 31.9]
inoff = [0.0] * len(USER)

placements = []
for j in range(len(cuts) - 1):
    s = cuts[j]
    d = round(cuts[j + 1] - cuts[j], 3)
    if d < 0.15:
        continue
    k = j % len(USER)
    ip = inoff[k]
    if ip + d > durs[k] - 0.1:
        ip = 0.0
    inoff[k] = ip + d
    placements.append((k, round(ip, 3), d))

print('segmentlar:', len(placements))

# har segmentni normallashtirib chiqaramiz (720x1280, 30fps, ovozsiz)
vf = 'scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,setsar=1'
listfile = TMP + '/list.txt'
with open(listfile, 'w', encoding='utf-8') as lf:
    for i, (k, ip, d) in enumerate(placements):
        out = f'{TMP}/seg_{i:03d}.mp4'
        cmd = [FF, '-y', '-ss', str(ip), '-i', USER[k], '-t', str(d),
               '-vf', vf, '-an', '-c:v', 'libx264', '-preset', 'veryfast',
               '-crf', '20', '-pix_fmt', 'yuv420p', out]
        subprocess.run(cmd, capture_output=True)
        lf.write(f"file '{out}'\n")
        print(f'  seg {i+1}/{len(placements)} tayyor', end='\r')
print('\nsegmentlar tayyor, birlashtirilmoqda...')

# concat + reel ovozi
concat_v = TMP + '/montage_noaudio.mp4'
subprocess.run([FF, '-y', '-f', 'concat', '-safe', '0', '-i', listfile,
                '-c', 'copy', concat_v], capture_output=True)

final = BASE + '/media/MONTAJ_final.mp4'
subprocess.run([FF, '-y', '-i', concat_v, '-i', MEDIA + '/reel_audio.m4a',
                '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac',
                '-b:a', '192k', '-shortest', final], capture_output=True)

sz = os.path.getsize(final) / 1024 / 1024
print(f'TAYYOR: {final} ({sz:.1f} MB)')
