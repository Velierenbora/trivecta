# SplatFlow — Video'dan 3D Gaussian Splat

Video yükle (tarayıcıdan, trycloudflare tüneli üzerinden) → otomatik olarak kamera
pozu çıkarılır (SfM) → 3D Gaussians eğitilir → sonuç tarayıcıda gezilir.

Motor: **Spirula Studio** (tek binary, Vulkan, GPU). Python/COLMAP gerekmez.

## Mimari
```
[Kullanıcı / müşteri tarayıcısı]
        │  HTTPS  (trycloudflare tüneli)
        ▼
[cloudflared]  ──►  [SplatFlow  FastAPI 127.0.0.1:8088]
                            │  (yerel, aynı PC)
                            ▼
                     [spirula.exe] ─ Vulkan ─ RTX 5070
                       1. ffmpeg ile H.264 + <=1920px normalize
                       2. sam extract  : en net kareler
                       3. sfm auto     : kamera pozlari (COLMAP formati)
                       4. train 3dgs   : Gaussian splat
                       5. (opsiyonel) mesh : oda yuzeyi (.glb)
                            ▼
                     result/splat.ply  → viewer
```

## Kullanim
1. `baslat.ps1` çalıştır (yeni URL üretir).
2. URL'yi tarayıcıda aç.
3. Bir **oda turu videosu** yükle.
4. Sonuç: 3B Gaussian görüntüleyici + `splat.ply` indirme.

## Ayarlar (ortam degiskenleri)
| Degisken | Varsayilan | Anlam |
|---|---|---|
| `SS_ITERS` | `10000` | Egitim adimi (kalite/sure) |
| `SS_QUALITY` | `medium` | `low\|medium\|high\|ultra` |
| `SS_EXTRACT_SKIP` | `3` | Kac karede bir ornek alinacak (1 = her kare) |
| `SS_EXTRACT_KEEP` | `2` | Son n karenin en neti |
| `SS_MAX_FRAMES` | `0` | En fazla kare (0 = **sinirsiz / tum video**) |
| `SS_MAX_EDGE` | `1920` | Video en uzun kenar (ffmpeg) |
| `SS_RES_DIVISOR` | `0` | Egitim cozunurluk boleni (2 = yari) |
| `SS_MESH` | `0` | `1` = ek olarak `mesh.glb` uret |

## Islem modlari (arayuzde secilir)
| Mod | Kareler | Adim | Kalite | Sure |
|---|---|---|---|---|
| `fast` | skip 6, max 250 | 5000 | low | ~1 dk |
| `standard` (varsayilan) | tum video, skip 3 | 10000 | medium | ~2 dk |
| `full` | **her kare**, skip 1 | 20000 | high | birkac dk (dosya buyuk) |


Ornek: daha hizli test icin
```powershell
$env:SS_ITERS="4000"; $env:SS_QUALITY="low"; $env:SS_EXTRACT_SKIP="6"
powershell -ExecutionPolicy Bypass -File .\baslat.ps1
```

## Dosyalar
- `server.py` — FastAPI sunucu (yukleme + durum + dosya servisi)
- `pipeline.py` — video → splat boru hatti
- `static/index.html` — yukleme arayuzu
- `static/viewer.html` — 3B Gaussian goruntuleyici
- `jobs/<id>/` — her isin girdisi ve sonucu
- `baslat.ps1` — yeniden baslatma

## Notlar
- Ayni anda **tek is** calisir (`GPU_LOCK`).
- `trycloudflare` URL'si gecicidir; yeniden baslatinca degisir.
- Video H.264/H.265/AV1 olmali; olmasa da ffmpeg otomatik cevirir.
- Lisans: Spirula Studio **GPL-3.0** (ic kullanim/MVP icin uygun).
