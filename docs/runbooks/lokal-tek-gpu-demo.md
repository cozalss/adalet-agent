# Runbook — Lokal Tek-GPU Demo (RTX 4070 12GB)

> ADALET tam-stack'ini **tek 12GB GPU**'lu bir Windows makinede ayağa kaldırıp
> denemek için doğrulanmış prosedür. **2026-06-03'te canlı doğrulandı**: gerçek Qwen
> cevabı + 16 kaynak + tahmin paneli (depozito senaryosu, `verdict=pass`).
>
> Tek komutla: **`bash scripts/run-local-demo.sh`** — bu belge o script'in *neden*
> böyle olduğunu ve sorun çıkarsa ne yapılacağını anlatır.

## TL;DR

```bash
# Ön-koşul: docker'da qdrant (adalet_mursit_hybrid dolu) + redis UP
bash scripts/run-local-demo.sh          # backend :8000 + frontend :5173 başlat
#   → http://localhost:5173  (kayıt/giriş → olgu-zengin soru)
bash scripts/run-local-demo.sh stop     # durdur
```

## Önkoşullar (başlamadan doğrula)

| Bileşen | Doğrulama | Beklenen |
|---------|-----------|----------|
| Qdrant + Redis | `docker ps` | `adalet-qdrant` + `adalet-redis` **Up** |
| Koleksiyon | `curl -s http://localhost:6333/collections/adalet_mursit_hybrid` | `points_count` ~159.769 (>0), 768-dim |
| GPU | `nvidia-smi` | **≥8 GB boş** (üretim Qwen3.5-9B Q4_K_XL ~6 GB ister) |
| Model | `ls backend/models/*.gguf` | `Qwen3.5-9B-UD-Q4_K_XL.gguf` (~6 GB) |
| Bağımlılık | `backend/.venv` + `frontend/node_modules` | ikisi de mevcut |

> `adalet-qdrant-dev` container'ı "unhealthy" görünebilir — o eski/ikinci kopya;
> asıl `:6333`'ü publish eden `adalet-qdrant` sağlıklıysa sorun yok.

## GPU yerleşim stratejisi (12 GB'a sığdırma)

> **Not:** Aşağıdaki yerleşim 14B (~10.7 GB) dönemine göre boyutlandırıldı; üretim
> Qwen3.5-9B'ye (~6 GB) geçtiğinden artık daha fazla VRAM başlığı var (yardımcı
> modeller GPU'da kalabilir). Bu Plan A tablosu güvenli **alt sınır** olarak korunur.

12 GB'a 14B **+** tüm yardımcı modeller (embedding/reranker/NLI/BERT ~4 GB)
**aynı anda sığmaz**dı. Plan A (güvenli, bu runbook): **GPU'da yalnız LLM**, gerisi CPU.

| Model | Karar | Env |
|-------|-------|-----|
| Qwen 14B (LLM) | **GPU** (tek sahip, ~10.7 GB) | `LLM_MODE=llamacpp` `LLM_N_GPU_LAYERS=-1` `LLM_N_BATCH=512` |
| Mursit embedder | CPU (+100-150ms/istek, görünmez) | `EMBEDDING_DEVICE=cpu` `EMBEDDING_FP16=0` |
| BGE-M3 sparse | **KAPALI** (~2 GB tasarruf) | `SPARSE_EMBEDDER_MODEL=` (boş) |
| reranker-tr-legal | CPU | `RERANKER_DEVICE=cpu` `RERANKER_FP16=0` |
| mDeBERTa NLI | GPU (kodda sabit, ~0.5 GB; Qwen+NLI=11.2<12) | (env yok) |
| BERT tahmin | CPU (RAM ~0.5 GB, GPU yemez) | `PREDICTIVE_DEVICE=cpu` |
| RAPTOR / GraphRAG | KAPALI | `RAPTOR_ENABLED=0` `GRAPH_RAG_ENABLED=0` |

Sonuç: GPU'da Qwen (~10.7) + NLI (lazy, ~0.5) = **~11.2 GB**, ~173 MB boş — sınırda
ama stabil çalışır. Çok uzun bir prompt OOM riski taşır; tipik sorular sorunsuz.

## ⚠️ Üç kritik tuzak (hepsi script'te çözülü)

1. **`LLM_SPECULATIVE=0` ZORUNLU.** In-process llamacpp'te prompt-lookup speculative
   decoding, **uzun prompt**ta (retrieval 16 kaynak) logits broadcast çökmesi yapar:
   `could not broadcast input array from shape (Nx) into shape (Ny)` → `draft_llm_failed`
   → cevap reddedilir ("doğrulanabilir iddia bulunamadı"). `0` = kapalı = draft çalışır.
2. **`python -m uvicorn` (uvicorn DEĞİL).** Windows "Uygulama Denetimi" (Application
   Control) `uvicorn.exe` console script'ini engeller: `Failed to spawn: uvicorn ...
   os error 4551`. Modül olarak çalıştır. (Aynı kural: `uv run python -m pytest`.)
3. **`node node_modules/vite/bin/vite.js` (pnpm dev DEĞİL).** Aynı Application Control
   sebebiyle `pnpm.cmd`/`vite.cmd` engellenebilir; doğrudan `node` ile çalıştır.

Ek: **`--reload` ASLA kullanma** (reloader subprocess Qwen'i 2. kez yükler → anında OOM).
**`ENV=development` zorunlu** (`ENV=production` + `AUTH_ENABLED=0` → güvenlik fail-fast çöker).

## Kimlik doğrulama akışı (misafir kaldırıldı)

`http://localhost:5173` açılınca doğrudan **AuthPage** gelir (commit `bb7cc00` misafir
modunu kaldırdı). Kayıt/giriş **Supabase** üzerinden (frontend doğrudan
`gbcrszrkytmxrybysqpu.supabase.co`'ya gider, backend `/auth`'a değil).

1. **Kayıt** sekmesi → e-posta + şifre (min 8) + gizlilik onayı → Hesap oluştur.
2. Supabase "e-postanı doğrula" derse → Dashboard ▸ Auth ▸ Email ▸ **Confirm email KAPAT**
   (dev için), ya da maildeki linke tıkla → sonra **Giriş**.
3. `/sor` açılır → soru sorulabilir.

**`AUTH_ENABLED=0` sınırı:** `/ask` (soru sorma) token'sız **çalışır**; ama `/me`,
`/me/conversations`, `/me/preferences` **401** döner → sol panel **geçmiş boş** kalır,
tercih kaydedilmez. Bu beklenen; soru-sorma akışı tam çalışır. Kalıcı geçmiş istenirse:
`AUTH_ENABLED=1` + `SUPABASE_JWT_SECRET` (.env'de boş) + `DATABASE_URL` (ayrı kurulum).

## Deneme — kanıtlanmış örnek

Olgu-zengin soru sor (yoksa Policy Engine **clarify**'a yönlendirir — tasarım gereği
ek bilgi ister). Doğrulanmış örnek:

> *"Kira sözleşmem geçen ay sona erdi, evi hasarsız teslim ettim ama ev sahibim
> 2 aydır 15000 TL depozitomu iade etmiyor. Ne yapabilirim?"*

Beklenen: `domain=kira`, `verdict=pass`, ~16 kaynak, zengin format (Durumunuza uygulama
→ Dayanak → Ne yapmalı), `[src: m-TBK-372]`/`[src: m-TBK-342]` atıfları, tahmin kartı,
zorunlu disclaimer. **İlk soru ~80 sn** (Qwen GPU'ya yüklenir), sonrakiler ~30-50 sn.

## Sorun giderme

| Belirti | Sebep | Çözüm |
|---------|-------|-------|
| Cevap hep "net yanıt veremiyorum" + logda `draft_llm_failed` + `broadcast` | speculative crash | `LLM_SPECULATIVE=0` (script'te var) |
| `Failed to spawn: uvicorn ... os error 4551` | Application Control | `python -m uvicorn` |
| Soru anında "şunu netleştirin" döner | olgu yetersiz → clarify | süre/tutar/ne-oldu ekle |
| `llama_decode ... out of memory` / startup OOM | VRAM taştı | başka GPU sürecini kapat; gerekirse `EMBEDDING_DEVICE=cpu` zaten açık |
| Geçmiş paneli boş | `AUTH_ENABLED=0` → `/me` 401 | beklenen; kalıcı geçmiş ayrı kurulum |
| Health `"llm":"mock"` | Qwen lazy-load (ilk /ask'te yüklenir) | normal; ilk soruyu sor |
| Loglar | — | `.run/backend-demo.out.log` · `.run/frontend-demo.out.log` |

## İlgili

- `scripts/run-local-demo.sh` — bu runbook'un çalıştırılabilir hâli
- `docs/runbooks/llm-production-setup.md` — production (llamacpp_server) kurulumu
- `docs/PROJE-DURUMU.md` §1, §7 — mimari + deployment bağlamı
