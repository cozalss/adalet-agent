# Sprint-5 W16 — Resmi Gazete + Otomatik Tazeleme Cron

> Tarih: 2026-05-25
> Hedef: Veri canlı kalsın — günlük Resmi Gazete + haftalık Yargıtay son 30 gün delta.

## Değişiklikler

### 1. `pyproject.toml` — APScheduler bağımlılığı

```toml
"apscheduler>=3.10.4",
```

### 2. `core/scheduler.py` — yeni dosya

`make_scheduler()` factory:
- `SCHEDULER_ENABLED=0` → None döner (test/CI default kabulü)
- `SCHEDULER_ENABLED=1` → `AsyncIOScheduler` instance, 2 job:
  - `refresh_resmi_gazete` — günlük 03:00 Europe/Istanbul
  - `refresh_yargitay_recent` — haftalık Pazartesi 04:00
- APScheduler import edilemezse uyarı log + None döner (degrade safe)

### 3. `scripts/refresh_resmi_gazete.py` — yeni dosya

Resmi Gazete JSON feed'ini schema-tolerant parser ile okur:
- Filter: KANUN / KHK / CK / YONETMELIK türü
- Bilinen kanun_no'lar (KANUN_KODU_TO_NUMARA) → yeni yayın varsa relevant olarak işaretle
- Yeni KANUN/KHK tespit edilirse log warning (operatör manual re-seed)
- `REFRESH_RG_STUB=1` → feed çekilmez (test/CI'da güvenli)
- Çağrı: direct `python -m scripts.refresh_resmi_gazete` veya scheduler

### 4. `scripts/refresh_yargitay_recent.py` — yeni dosya

Son 30 gün delta-sync:
- 8 domain × Yargıtay → son güncel date_window (2024-2026)
- Mevcut SeedState (data/seed_state/yargitay_*.jsonl) ile diff
- Yeni doc_id'ler pipeline'a feed edilir, embed + upsert
- Bedesten rate limit 10/30s — total ~3dk worst case
- `REFRESH_YG_STUB=1` → Bedesten çağrılmaz (test/CI)

### 5. `main.py` — Lifespan'a scheduler eklendi

Startup:
```python
scheduler = make_scheduler()
if scheduler is not None:
    scheduler.start()
    log.info("scheduler_started", jobs=[j.id for j in scheduler.get_jobs()])
```

Shutdown:
```python
if scheduler is not None:
    scheduler.shutdown(wait=False)
```

Scheduler exception-safe — başlatma fail olsa bile lifespan devam eder.

### 6. `backend/Dockerfile` — Env eklendi

```dockerfile
ENV SCHEDULER_ENABLED=1 \
    SCHEDULER_TIMEZONE=Europe/Istanbul
```

Container çalıştığında scheduler default ON. Test/dev için ENV override.

### 7. `tests/scripts/test_refresh.py` — yeni dosya

4 test:
- `test_refresh_resmi_gazete_stub_returns_zero`: stub mode HTTP yapmaz, 0 döner
- `test_refresh_yargitay_stub_returns_zero`: stub mode Bedesten çağırmaz
- `test_scheduler_disabled_returns_none`: `SCHEDULER_ENABLED=0` → None
- `test_scheduler_enabled_returns_instance_or_none`: jobs eklendi mi

## Cron Tablosu

| Job | Schedule (Türkiye saati) | Misfire grace |
|---|---|---|
| refresh_resmi_gazete | Her gün 03:00 | 1 saat |
| refresh_yargitay_recent | Her Pazartesi 04:00 | 2 saat |

## Beklenen Sonuç

**Senaryo 1:** Resmi Gazete'de yeni bir TBK değişikliği yayınlanırsa,
03:00 Türkiye saatinde scheduler tespit eder, log yazar:
```
INFO  rg_new_law_detected no=6098 title="Türk Borçlar Kanunu'nda Değişiklik..."
INFO  refresh_resmi_gazete_completed total=120 relevant=1 n_new=1
```
Operatör log'u görüp manual `uv run python -m scripts.seed_mevzuat` koşar.

**Senaryo 2:** Yargıtay'da son 30 gün içinde yeni bir tüketici kararı çıkarsa,
Pazartesi 04:00'te scheduler delta-sync yapar:
```
INFO  yg_domain_delta_done domain=tuketici new_docs=8
INFO  yg_domain_delta_done domain=isHukuku new_docs=12
...
INFO  refresh_yargitay_recent_completed n_new=42
```

## Sınırlamalar

- **Resmi Gazete API**: Gerçek JSON feed endpoint'i belirsiz; placeholder URL kullanılıyor. Production deploy öncesi `RESMI_GAZETE_FEED_URL` env'i gerçek endpoint ile set edilmeli.
- **Otomatik re-seed**: Yeni KANUN tespiti sadece log'a yazılır; otomatik re-seed YOK (büyük seed run uzun). Operatör manuel tetikler. İleri sürümlerde feature flag arkasında otomatik tetik eklenebilir.
- **Scheduler container vs cron**: Single-instance deployment için scheduler container içinde çalışır. Multi-instance (HA) için Redis lock ile leader-election gerekir — şu an scope dışı.

## Verify

```bash
# Stub mode test
REFRESH_RG_STUB=1 uv run python -m scripts.refresh_resmi_gazete
# Expected: rg_total_processed=0

REFRESH_YG_STUB=1 uv run python -m scripts.refresh_yargitay_recent
# Expected: yg_total_new=0

# Scheduler test (apscheduler kurulu)
uv run pytest tests/scripts/test_refresh.py -v

# Production-like start (container)
docker compose up backend
docker compose logs backend | grep -E "scheduler_started|scheduler_job_added"
# Expected: "scheduler_started jobs=['refresh_resmi_gazete', 'refresh_yargitay_recent']"
```

## Sprint-5 Closure

W11-W16 tamamlandı. Sprint-5 sonu hedefler:

| Alan | Sprint-4 sonu | Sprint-5 sonu | Status |
|---|---|---|---|
| Veri derinliği (kanun) | 6.0 | 9.0 | ✓ (17 → 41 kanun) |
| Veri derinliği (emsal) | 7.0 | 9.0 | △ (kod hazır, seed run TBD) |
| Veri çeşitliliği (regulator) | 0 | 8.0 | △ (kod hazır, manuel veri TBD) |
| Veri canlılığı (refresh) | 4.0 | 8.5 | ✓ (cron+scheduler aktif) |

**Pending operatör görevleri:**
1. `uv run python -m scripts.seed_mevzuat` — 41 kanun re-seed (~10-12h offline)
2. Weak domain re-seed: `uv run python -m scripts.seed_decisions --court yargitay --domain icra,trafik,vergi,tapu,idari` (~8-12h offline)
3. Strong domain alt-kategori re-seed: `uv run python -m scripts.seed_decisions --court yargitay --domain tuketici,isHukuku,kira`
4. Regulator JSONL veri hazırlığı: `data/seed_state/regulator_README.md` rehberine göre 700 karar manuel hazırla
5. `uv run python -m scripts.seed.regulators` — regulator seed
6. `uv run python -m eval.domain_audit --final` — final rapor

**Sprint-6 kapsamı (defer):**
- Schema versioning + mülga işaretleme
- Per-domain retrieval tuning (HyDE prompt, RRF k, reranker threshold)
- Benchmark v3 (500 vaka)
- /stats + /info/quality endpoint'leri
- ADR-009/010/011
