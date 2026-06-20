# Dokümantasyon Yönetişimi

Bu proje dokümantasyonu “çok yazı” ile değil, **izlenebilir ve güncel iddia** disipliniyle yönetilir. Amaç: jürinin, geliştiricinin veya hakemin herhangi bir sayıyı, model iddiasını ya da ürün davranışını hangi koşulda doğrulayacağını hemen görebilmesi.

## Hiyerarşi

1. `docs/CURRENT_STATUS.md`: güncel ürün durumu ve doğrulama kapıları için tek doğru kaynak.
2. `README.md`: kullanıcı ve geliştirici giriş kapısı; güncel iddialar `CURRENT_STATUS` ile uyumlu olmalıdır.
3. `docs/architecture.md`: güncel mimari açıklama; tarihsel sprint notları açıkça tarihsel kalabilir.
4. Runbook'lar: operasyonel talimat verir; hangi ortam için geçerli olduğunu başta söyler.
5. Tez, audit, ablation, changelog ve proje durumu belgeleri: tarihsel/snapshot belgelerdir; güncel iddia gibi okunmamalıdır.

## Metrik Yazma Kuralı

Bir metrik veya başarı iddiası yazılıyorsa yanında şu bilgiler bulunmalıdır:

- Tarih ve mümkünse saat dilimi.
- Komut veya ölçüm aracı.
- Veri seti/korpus adı ve büyüklüğü.
- Model adı ve çalışma modu.
- Mock/fast suite mi, canlı entegrasyon mu olduğu.
- Dışarıda bırakılan test veya bileşenler.
- Beklenen sonuç ve gözlenen sonuç.

Örnek doğru ifade:

```text
2026-06-21 fast suite: LLM_MODE=mock ile backend hızlı test paketi çalıştırıldı; multimodal/training/real LLM e2e hariç, 1532 test geçti.
```

Örnek sakıncalı ifade:

```text
Tüm sistem tamamen test edildi.
```

## Yasak Belirsizlikler

- “Güncel” kelimesi tarih olmadan kullanılmaz.
- Test sayısı eski dokümandan kopyalanmaz; önce komut yeniden çalıştırılır veya `CURRENT_STATUS` referans verilir.
- “Sıfır halüsinasyon” mutlak garanti gibi yazılmaz; ölçülen hedef, güvenlik katmanı veya belirli benchmark sonucu olarak yazılır.
- Model adı tek başına yazılmaz; o ölçümde kullanılan model mi, repo-configured production model mi olduğu belirtilir.
- Tarihsel Qwen 2.5 14B ablation sonucu, güncel Qwen3.5-9B üretim sonucu gibi sunulmaz.
- “Misafir modu” güncel web ürünü için yazılmaz; Supabase auth güncel gereksinimdir.

## Snapshot Banner Kuralı

Tarihsel belgelerin başında şu bilgilerden en az biri bulunmalıdır:

- Ölçüm tarihi.
- “Tarihsel snapshot” veya “güncel durum için `docs/CURRENT_STATUS.md`” uyarısı.
- Model/veri seti farkı.
- O belgenin hangi amaçla saklandığı.

## PR / Değişiklik Kontrol Listesi

Bir değişiklik ürün davranışını, test sayısını, model adını, auth akışını, güvenlik iddiasını veya değerlendirme sonucunu etkiliyorsa:

- `docs/CURRENT_STATUS.md` güncellendi mi?
- README'deki özet iddia hala doğru mu?
- Tarihsel belgeye yeni metrik eklendiyse tarih/komut/model yazıldı mı?
- Eski sayılar “current” gibi görünüyorsa banner eklendi mi?
- `scripts/check_docs_consistency.py` geçti mi?

## Bakım Ritmi

- Her büyük doğrulama koşusundan sonra `CURRENT_STATUS` güncellenir.
- Her release veya yarışma başvurusu öncesinde README, `docs/README.md`, yarışma özeti ve `CURRENT_STATUS` birlikte okunur.
- Eski belgeler silinmez; ama tarihsel oldukları üstte açıkça işaretlenir.
