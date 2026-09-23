# Premiere ko'prigiga buyruq yuborib, javobni kutadigan yordamchi
import json, time, os

DIR = os.path.dirname(os.path.abspath(__file__))
CMD = os.path.join(DIR, 'cmd.json')
RES = os.path.join(DIR, 'result.json')


def run(script, timeout=40):
    cid = int(time.time() * 1000) % 1000000000
    with open(CMD, 'w', encoding='utf-8') as f:
        json.dump({'id': cid, 'script': script}, f)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with open(RES, encoding='utf-8') as f:
                r = json.load(f)
            if r.get('id') == cid:
                return r
        except Exception:
            pass
        time.sleep(0.8)
    return {'ok': False, 'result': 'timeout'}
