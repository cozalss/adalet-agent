# Dokümantasyon

Bu klasörde güncel ürün belgeleri, operasyon runbook'ları, tarihsel ölçüm snapshot'ları ve tez/audit belgeleri birlikte yaşar. Güncel durum için önce şu dosyadan başlayın:

- [CURRENT_STATUS.md](CURRENT_STATUS.md) — güncel tek doğru kaynak: ürün kapsamı, doğrulama matrisi, model/korpus notları
- [DOCUMENTATION_GOVERNANCE.md](DOCUMENTATION_GOVERNANCE.md) — metrik, snapshot ve güncellik kuralları
- [architecture.md](architecture.md) — sistem mimarisi, ajan akışı, veri akışı, yol haritası
- [data-pipeline.md](data-pipeline.md) — veri alma katmanları (bulk + live + verify)
- [runbooks/](runbooks/) — üretim ve operasyon talimatları
- [audit/](audit/) — tarihsel denetim çıktıları ve backlog kayıtları
- [theses/](theses/) — bitirme tezi taslakları ve ölçüm snapshot'ları

## Okuma Sırası

1. Güncel puan ve doğrulama için `CURRENT_STATUS.md`.
2. Sistem nasıl çalışıyor sorusu için `architecture.md`.
3. Metriklerin nasıl yazılacağı ve eski belgelerin nasıl okunacağı için `DOCUMENTATION_GOVERNANCE.md`.
4. Akademik/yarışma anlatısı için `yarisma-ozeti.md`, `ablation_study.md` ve `theses/`.

Tarihsel belgelerdeki eski model adları, test sayıları veya audit bulguları tek başına güncel durum sayılmaz. Güncel iddia ile çelişki görürseniz `CURRENT_STATUS.md` esas alınır.
