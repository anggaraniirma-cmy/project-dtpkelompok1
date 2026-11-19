"""Uji integrasi LIVE dengan webcam nyata (bukan mock).

Menjalankan alur sungguhan terhadap backend yang sedang hidup:
  1. health
  2. kamera mode battle start -> MediaPipe with num_hands=2
  3. stream MJPEG menerima frame
  4. /api/battle/start + state
  5. WebSocket /api/cv/ws/battle mengirim status dua pemain
  6. /api/cv/photo-frame mengembalikan JPEG yang benar
  7. kamera dilepas

Laporan dicetak apa adanya; bila tidak ada tangan di depan kamera, skrip
mengatakan begitu — tidak mengarang hasil.
"""
from __future__ import annotations

import json
import sys
import time

import httpx
from websockets.sync.client import connect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
WS = BASE.replace("http://", "ws://").replace("https://", "wss://")
ok_all = True


def cek(label: str, kondisi: bool, detail: str = "") -> None:
    global ok_all
    status = "LULUS" if kondisi else "GAGAL"
    if not kondisi:
        ok_all = False
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))


with httpx.Client(timeout=30) as c:
    print("1) health")
    h = c.get(f"{BASE}/api/health").json()
    cek("backend hidup", h.get("status") == "ok", json.dumps(h))

    print("2) kamera mode battle")
    c.post(f"{BASE}/api/cv/stop")
    r = c.post(f"{BASE}/api/cv/start?mode=battle")
    cek("kamera battle menyala", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text)
        sys.exit(1)
    mode = r.json().get("mode")
    cek("mode terkonfirmasi battle", mode == "battle", str(mode))

    # beri waktu pipeline memproses beberapa frame
    time.sleep(2.0)

    print("3) stream MJPEG")
    with c.stream("GET", f"{BASE}/api/cv/stream") as resp:
        cek("stream HTTP 200", resp.status_code == 200)
        buf = b""
        deadline = time.time() + 6
        for chunk in resp.iter_bytes():
            buf += chunk
            if b"--frame" in buf and b"\xff\xd8" in buf:
                break
            if time.time() > deadline:
                break
    cek("frame JPEG diterima", b"\xff\xd8" in buf, f"{len(buf)} byte")

    print("4) battle session")
    c.post(f"{BASE}/api/battle/reset")
    r = c.post(f"{BASE}/api/battle/start", json={"jumlah_soal": 3,
                                                 "nama_pemain_1": "Rina",
                                                 "nama_pemain_2": "Budi"})
    cek("sesi battle dibuat", r.status_code == 200, f"HTTP {r.status_code}")
    st = r.json()
    cek("dua pemain ada", set(st.get("pemain", {}).keys()) == {"1", "2"},
        str(list(st.get("pemain", {}).keys())))
    cek("skor awal nol", st["pemain"]["1"]["skor"] == 0 and st["pemain"]["2"]["skor"] == 0)

    print("5) WebSocket /api/cv/ws/battle")
    frames = []
    try:
        with connect(f"{WS}/api/cv/ws/battle", open_timeout=10) as ws:
            t0 = time.time()
            while time.time() - t0 < 4:
                try:
                    msg = json.loads(ws.recv(timeout=2))
                except Exception:
                    break
                if msg.get("tipe") == "status":
                    frames.append(msg)
                    if len(frames) >= 3:
                        break
        cek("menerima status WS", len(frames) > 0, f"{len(frames)} payload")
        if frames:
            last = frames[-1]
            cam = last.get("kamera") or {}
            cek("payload punya pemain 1 & 2",
                isinstance(cam.get("pemain"), dict) and
                set(cam["pemain"].keys()) == {"1", "2"},
                str(list((cam.get("pemain") or {}).keys())))
            cek("payload punya state game",
                isinstance(last.get("game"), dict), str(bool(last.get("game"))))
            p1 = (cam.get("pemain") or {}).get("1", {})
            p2 = (cam.get("pemain") or {}).get("2", {})
            print(f"       fps={cam.get('fps')} P1 terdeteksi={p1.get('terdeteksi')} "
                  f"P2 terdeteksi={p2.get('terdeteksi')}")
            if not p1.get("terdeteksi") and not p2.get("terdeteksi"):
                print("       (tidak ada tangan di depan kamera saat tes — normal)")
    except Exception as exc:
        cek("WebSocket battle terhubung", False, str(exc))

    print("6) photo frame")
    r = c.get(f"{BASE}/api/cv/photo-frame")
    cek("photo-frame HTTP 200", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code == 200:
        cek("isi JPEG valid", r.content[:2] == b"\xff\xd8",
            f"{len(r.content)} byte, content-type={r.headers.get('content-type')}")

    print("7) lepas kamera")
    r = c.post(f"{BASE}/api/cv/stop")
    cek("kamera dilepas", r.status_code == 200, r.json().get("pesan", ""))
    live = c.get(f"{BASE}/api/cv/live").json()
    cek("status tidak aktif", live.get("aktif") is False)
    r = c.get(f"{BASE}/api/cv/photo-frame")
    cek("photo-frame 503 setelah kamera mati", r.status_code == 503)

    print("8) single player masih utuh")
    c.post(f"{BASE}/api/game/reset")
    r = c.post(f"{BASE}/api/game/start", json={"jumlah_soal": 2})
    cek("single player start OK", r.status_code == 200, f"HTTP {r.status_code}")
    cek("state single tidak punya pemain", "pemain" not in r.json())
    c.post(f"{BASE}/api/game/reset")

print()
print("HASIL:", "SEMUA LULUS" if ok_all else "ADA YANG GAGAL")
sys.exit(0 if ok_all else 1)
