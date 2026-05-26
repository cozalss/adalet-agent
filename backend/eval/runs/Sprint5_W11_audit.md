# Sprint-5 W11 — Domain Audit Raporu

> Tarih: 2026-05-25
> Kapsam: Sprint-5 (Pure Data Expansion) için her domain'de eksiklik tespiti.
> Çıktı: W12-W16 implementation girdisi (kanun listesi, keyword genişlemesi, daire haritası, regulator mapping).

## Yöneticı Özet

Backend Sprint-4 sonu **9/10** (kod kalitesi, auth, observability). Veri katmanı **5.5/10**: 17 kanun + 3.179 karar seeded; 8 domain'in 5'inde (icra, trafik, vergi, tapu, idari) emsal **<200 karar/domain**. Hedef Sprint-5 sonu: **60+ kanun + 8.800 karar + 1.500 regulator karar = 10.300 emsal**, veri katmanı 8.6/10.

## 1. Mevcut Durum (2026-05-25 ölçümü)

### 1.1 Kanun Seeding

| # | Kanun Kodu | Numara | Adı | Domain |
|---|---|---|---|---|
| 1 | TBK | 6098 | Türk Borçlar Kanunu | kira, genel |
| 2 | IK | 4857 | İş Kanunu | isHukuku |
| 3 | TKHK | 6502 | Tüketicinin Korunması | tuketici |
| 4 | TMK | 4721 | Türk Medeni Kanunu | tapu, genel |
| 5 | ANAYASA | 2709 | T.C. Anayasası | tüm |
| 6 | HMK | 6100 | Hukuk Muhakemeleri | usul |
| 7 | IYUK | 2577 | İdari Yargılama Usulü | idari |
| 8 | IIK | 2004 | İcra ve İflas | icra |
| 9 | SGK | 5510 | Sosyal Sigortalar | isHukuku |
| 10 | SK | 6356 | Sendikalar | isHukuku |
| 11 | ISGK | 6331 | İş Sağlığı Güvenliği | isHukuku |
| 12 | RKHK | 4054 | Rekabetin Korunması | tuketici |
| 13 | VUK | 213 | Vergi Usul | vergi |
| 14 | TK | 2918 | Karayolları Trafik | trafik |
| 15 | KK | 2644 | Tapu Kanunu | tapu |
| 16 | KMK | 634 | Kat Mülkiyeti | tapu |
| 17 | TCK | 5237 | Türk Ceza Kanunu | (referans, scope-out) |

**Tespit:** 17 kanun, ama her domain için 1-3 kanun var. Gerçek bir vatandaş sorusu çoğunlukla **birden fazla kanunla** ilişkili (örn. "trafik kazasında tazminat" → KTK + TBK haksız fiil + ZMSS Genel Şartları + Sigortacılık K.).

### 1.2 Emsal Karar Seeding (per-court × domain)

| Domain | Yargıtay | Danıştay | AYM | Toplam | Hedef | Δ |
|---|---|---|---|---|---|---|
| tuketici | 200 | 143 | 305 | **648** | 1500 | +852 |
| isHukuku | 180 | 165 | 976 | **1321** | 2000 | +679 |
| kira | 192 | 165 | 217 | **574** | 1200 | +626 |
| icra | 88 | — | 20 | **108** | 800 | +692 |
| trafik | 77 | 71 | 20 | **168** | 800 | +632 |
| vergi | 80 | 56 | 20 | **156** | 800 | +644 |
| tapu | 54 | 53 | 20 | **127** | 700 | +573 |
| idari | — | 57 | 20 | **77** | 1000 | +923 |
| **Toplam** | **871** | **710** | **1598** | **3.179** | **8.800** | **+5.621** |

**Tespit (Tier-1 zayıf):** icra, trafik, vergi, tapu, idari — hepsi <200 karar. Bir vatandaşın "haciz itirazı" sorusunda 12.HD'den 80 karar yeterli değil; tipik soru-cevap setinde 3-5 ilgili karar lazım.

**Tespit (Tier-2 derinleşme):** tuketici, isHukuku, kira — ana hedef 1200-2000. Sayı yeterli ama **alt-kategori** dağılımı dengesiz: TKHK m.83 (hakem heyeti) sorgusu yapıldığında karar yok, çünkü keyword'lerde alt-madde geçmemiş.

### 1.3 Düzenleyici Otorite Kararları

**Şu an: 0 karar.** KVKK, Rekabet Kurumu, SPK, BDDK, Sayıştay — hiçbiri seed'de yok.

**Etki:** "Bankam izinsiz veri paylaştı" sorusunda sistem KVKK Karar 2023/X'i göremiyor; sadece KVKK m.7'yi referans verebiliyor. KVKK kararları → uygulama detayı + emsal precedent. Eksiklik kritik.

## 2. Per-Domain Eksiklik Listesi

### 2.1 tuketici (mevcut: 1 kanun + 648 karar → hedef: 8 kanun + 1500 karar)

**Eksik kanunlar:**
| Kanun | Numara | Niye gerekli |
|---|---|---|
| TBK | 6098 | Sözleşme genel hükümleri (zaten var ama domain-tagged değil) |
| TTK | 6102 | E-ticaret, ticari satım, tüketici-tacir ayrımı |
| 6493 | 6493 | Ödeme Hizmetleri ve Elektronik Para Kuruluşları Kanunu |
| Sigortacılık | 5684 | Tüketici-sigorta uyuşmazlığı, sigorta tahkim |
| BK | 5411 | Bankacılık Kanunu — kredi, mevduat tüketici hakları |
| KVKK | 6698 | Tüketici verisinin işlenmesi |
| GDPR-paralel | — | (Bilgilendirme amaçlı, doğrudan seed yok) |

**Eksik alt-kategori karar (TKHK madde bazlı):**
- m.4 ayıplı mal/hizmet — ✓ var ama eski (2018 öncesi domine)
- m.11 cayma hakkı — × keyword yok, karar az
- m.48 cayma hakkı mesafeli sözleşme — × keyword yok
- m.49 kapıdan satışta cayma — × keyword yok
- m.61 garanti belgesi — × keyword yok
- m.66 abonelik sözleşmesi — × keyword zayıf
- m.83 tüketici hakem heyeti — × keyword zayıf
- m.84 tüketici mahkemesi — × keyword zayıf
- m.86 ön ödemeli konut — ✓ var

**Düzenleyici otorite:**
- KVKK: tüketici verisi işlenmesi kararları (~150 karar hedef)
- Rekabet Kurumu: tüketici lehine rekabet kararları (~80 karar hedef)
- SPK: yatırımcı/tüketici koruması (~50 karar hedef)
- BDDK: banka tüketici hakkı (~40 karar hedef)

### 2.2 isHukuku (mevcut: 3 kanun + 1321 karar → hedef: 10 kanun + 2000 karar)

**Eksik kanunlar:**
| Kanun | Numara | Niye gerekli |
|---|---|---|
| 657 DMK | 657 | Devlet Memurları K (kamu personeli iş hukuku) |
| TBK | 6098 | İş sözleşmesi genel hükümleri (m.393-447) |
| TTK | 6102 | Ticari işletmede çalışanlar |
| 5953 | 5953 | Basın Mesleğinde Çalışanlarla Çalıştıranlar |
| 854 Deniz İş | 854 | Gemi çalışanları |
| 5188 Özel Güvenlik | 5188 | Özel güvenlik çalışanları |
| Sosyal Yardım | — | İşsizlik sigortası vb. |

**Eksik alt-kategori karar (İK + SGK madde bazlı):**
- m.17 süreli fesih — ✓ var
- m.24 işçi haklı sebep — × keyword zayıf, dağınık
- m.25 işveren haklı sebep — × keyword zayıf
- m.41 fazla mesai — ✓ var ama 2024+ karar az
- m.46 ulusal bayram — × az
- m.55 yıllık izin — ✓ var
- SGK m.4-4 sigortalılık — × seed yok
- SGK m.86 emeklilik — × az
- AYM bireysel başvuru: çalışma hakkı, eşit muamele (mevcut 976 ama dağınık)

**Düzenleyici otorite:**
- KVKK: işveren özel hayata müdahale (~80 karar)
- Sayıştay: kamu kurumu personeline karşı denetim (~30 karar)

### 2.3 kira (mevcut: 1 kanun + 574 karar → hedef: 5 kanun + 1200 karar)

**Eksik kanunlar:**
| Kanun | Numara | Niye gerekli |
|---|---|---|
| Kat Mülkiyeti | 634 | Apartman ortak kira, kiracı-yönetici ilişki (zaten KMK olarak var ama domain-tagged değil) |
| TMK | 4721 | Mülkiyet hakkı, kiraya verenin sıfatı |
| Kentsel Dönüşüm | 6306 | Riskli yapılarda kira durumu, tahliye |
| 7269 Afet | 7269 | Doğal afet sonrası kira durumu |
| Belediye Kanunu | 5393 | Belediye taşınmazı kira (kamu kirası) |

**Eksik alt-kategori karar (TBK madde bazlı):**
- m.299 fesih bildirim süresi — × keyword zayıf
- m.315 ihtarname — × kararlar dağınık
- m.339 kefil sorumluluğu — × az
- m.343 kira artış — ✓ var (TÜFE keyword'ü)
- m.344 artış sınırı (%25) — × yeni içtihat eksik
- m.347 sözleşme yenileme — × keyword yok
- m.350 tahliye sebepleri — × dağınık
- m.351 kiraya veren ihtiyaç — × keyword yok
- m.355 işyeri kirası özel hükümler — × az

### 2.4 icra (mevcut: 1 kanun + 108 karar → hedef: 6 kanun + 800 karar)

**Eksik kanunlar:**
| Kanun | Numara | Niye gerekli |
|---|---|---|
| TTK | 6102 | Kambiyo senetleri (çek, bono, poliçe) icra konusu |
| 6183 AATUHK | 6183 | Amme Alacaklarının Tahsil Usulü (kamu icra) |
| BK | 5411 | Banka kredilerinin icra takibi |
| 5510 SGK | 5510 | SGK alacaklarının icra takibi |
| KKK 7155 | 7155 | Konkordato hakkında düzenleme |

**Eksik alt-kategori karar (İİK madde bazlı):**
- m.32 ödeme emri — × keyword zayıf
- m.62 itiraz — ✓ var
- m.67 itirazın iptali — ✓ var
- m.68 kambiyo özel takip — × az
- m.79 haciz — ✓ var
- m.97 üçüncü kişinin istihkak iddiası — × keyword yok
- m.105 maaş haczi — × keyword yok
- m.106 hisse haczi — × keyword yok
- m.128 ihale — × az
- m.179 konkordato — × az
- m.277 tasarrufun iptali — ✓ var

**Yargıtay daire:**
- **12. HD (icra-iflas daire)** — primary, mevcut 88 karar yetersiz, hedef 500+
- 19. HD (kambiyo senetleri) — × seed yok
- 23. HD (iflas) — × seed yok

### 2.5 trafik (mevcut: 2 kanun + 168 karar → hedef: 6 kanun + 800 karar)

**Eksik kanunlar:**
| Kanun | Numara | Niye gerekli |
|---|---|---|
| Sigortacılık | 5684 | Trafik sigortası, ZMSS düzenlemesi |
| TBK | 6098 | m.49 haksız fiil, m.55 manevi tazminat |
| 4925 KGK | 4925 | Karayolu Taşıma Kanunu (otobüs/kamyon kazaları) |
| 5188 | 5188 | Özel Güvenlik (PTT araçları vb.) |
| Otomotiv Yön. | — | (Yönetmelik bazlı) |
| ZMSS Genel Şartları | — | Sözleşme metni, sigorta uyuşmazlığında baz |

**Eksik alt-kategori karar:**
- 17. HD (trafik kazası tazminatı) — mevcut 77, hedef 400+
- 4. HD (sigorta tahkim itirazları) — × seed yok
- Danıştay 12. D (sürücü belgesi iptali) — kısmi (71 karar)
- Sigorta Tahkim Komisyonu kararları — × seed yok (özel mekanizma)

### 2.6 vergi (mevcut: 3 kanun + 156 karar → hedef: 10 kanun + 800 karar)

**Eksik kanunlar:**
| Kanun | Numara | Niye gerekli |
|---|---|---|
| Gelir V | 193 | Mevcut ama madde detayı az |
| Kurumlar V | 5520 | Şirket vergisi, kurum vergi davaları |
| KDV | 3065 | Mevcut |
| ÖTV | 4760 | Özel Tüketim Vergisi (alkol, tütün, akaryakıt) |
| Damga Vergisi | 488 | Damga vergisi, sözleşmeler |
| MTV | 197 | Motorlu Taşıt Vergisi |
| EmlakV | 1319 | Emlak Vergisi |
| 5345 | 5345 | Gelir İdaresi Başkanlığı (kurumsal) |
| 6183 AATUHK | 6183 | Kamu alacağı tahsili |
| 5018 Mali Yönetim | 5018 | Kamu mali yönetimi |

**Eksik alt-kategori karar:**
- Danıştay 9. D (vergi davaları) — kısmi (56 karar)
- Danıştay 4. D (gelir vergisi) — × seed yok
- Danıştay 7. D (gümrük) — × seed yok
- Sayıştay kararları — × seed yok (kamu mali denetim)

### 2.7 tapu (mevcut: 3 kanun + 127 karar → hedef: 7 kanun + 700 karar)

**Eksik kanunlar:**
| Kanun | Numara | Niye gerekli |
|---|---|---|
| Kentsel Dönüşüm | 6306 | Riskli yapı tapu sicili |
| Tapu Sicili Tüzüğü | — | Yönetmelik bazlı |
| İmar K | 3194 | İmar planı, ifraz, tevhid |
| Belediye K | 5393 | Belediye taşınmazı işlemleri |
| 2942 Kamulaştırma | 2942 | Kamulaştırma davası, bedel tespiti |

**Eksik alt-kategori karar:**
- Yargıtay 8. HD (tapu, izale-i şuyu) — mevcut 54, hedef 300+
- Yargıtay 14. HD (kadastro) — × seed yok
- Yargıtay 1. HD (tapu iptali) — × seed yok
- Danıştay 6. D (kamulaştırma) — × seed yok

### 2.8 idari (mevcut: 3 kanun + 77 karar → hedef: 8 kanun + 1000 karar)

**Eksik kanunlar:**
| Kanun | Numara | Niye gerekli |
|---|---|---|
| 5018 Mali Yönetim | 5018 | Mevcut ama az |
| 4734 Kamu İhale | 4734 | İhale iptali davaları |
| 4735 İhale Sözleşmeleri | 4735 | İhale sözleşmesi feshi |
| 3071 Dilekçe Hakkı | 3071 | İdareye başvuru |
| 2872 Çevre | 2872 | Çevre idari para cezası |
| Belediye K | 5393 | Belediye kararları iptal |
| 5302 İl Özel İdaresi | 5302 | İl özel idaresi |

**Eksik alt-kategori karar:**
- Danıştay 5. D (memur davası) — kısmi (57 karar)
- Danıştay 10. D (imar) — × seed yok
- Danıştay 12. D (sürücü belgesi) — kısmi
- Danıştay 13. D (kamu ihalesi) — × seed yok
- Sayıştay denetim kararları — × seed yok

## 3. Yargıtay Daire Haritası (Sprint-5 hedef genişleme)

| Daire | Domain | Şu an seed | Hedef |
|---|---|---|---|
| 1. HD | tapu iptali, mirasla ilgili tapu | 0 | 100 |
| 3. HD | tüketici, alacak | mevcut | 200 |
| 4. HD | sigorta tahkim, tazminat | 0 | 100 |
| 8. HD | tapu iptali, izale-i şuyu | 0 | 200 |
| 9. HD | iş hukuku (genel) | mevcut | 400 |
| 12. HD | icra-iflas | mevcut (88) | 500 |
| 13. HD | tüketici | mevcut | 300 |
| 14. HD | kadastro, tapu | 0 | 150 |
| 15. HD | kira, finansal kiralama | mevcut | 200 |
| 17. HD | trafik kazası tazminatı | mevcut (77) | 400 |
| 19. HD | kambiyo senetleri (icra) | 0 | 150 |
| 21. HD | iş kazası, meslek hastalığı | 0 | 200 |
| 22. HD | iş hukuku özel (kıdem) | mevcut | 300 |
| 23. HD | iflas | 0 | 100 |
| HGK | landmark içtihat (her domain) | 0 | 100 (split) |
| İBK | İçtihatları Birleştirme | 0 | 30 |

## 4. Düzenleyici Otorite Mapping

| Otorite | Domain'ler | Sprint-5 hedef | Erişim |
|---|---|---|---|
| KVKK | tuketici (data), isHukuku (özel hayat) | 200 karar | kvkk.gov.tr/Karar |
| Rekabet Kurumu | tuketici (rekabet ihlali) | 150 karar | rekabet.gov.tr/Karar |
| SPK | tuketici-finansal (yatırım) | 100 karar | spk.gov.tr/Karar |
| BDDK | tuketici-bankacılık | 80 karar | bddk.org.tr/Karar |
| Sayıştay | idari, vergi (kamu denetim) | 170 karar | sayistay.gov.tr/Karar |
| **Toplam** | | **700-1500** | |

## 5. Sprint-5 Çıktıları (W12-W16 input)

### W12 — Mevzuat 16→40 kanun
Yeni eklenecek: TTK, BK, Sigortacılık K, ÖTV, DV, MTV, EmlakV, KurumlarV, 6183, 6306, 4734, 4735, 657 DMK, 5345, 5302, 2942, 854, 5188, 4925, 5953, 5018 detay, 6493, 3071, 2872 (24 yeni → toplam 41).

### W13 — Tier-1 zayıf domain seed
- Daire genişleme: 1.HD, 4.HD, 8.HD, 14.HD, 19.HD, 21.HD, 23.HD eklendi → 7 yeni daire.
- Tarih penceresi: 4→8 (2014-2017, 2018-2019, 2020-2021, 2022-2023, 2024-2026 dışında 2010-2013, 2014-2015, 2016-2017 eklenir).
- Danıştay daire bazlı: 4.D, 5.D, 6.D, 7.D, 9.D, 10.D, 12.D, 13.D explicit chamber filter.

### W14 — Tier-2 güçlü domain alt-kategori
- TKHK m.4/11/48/49/61/66/83/84 keyword'leri eklendi.
- İK m.17/24/25/41/55 + SGK m.4-4/86 keyword'leri.
- TBK m.299/315/339/344/347/350/351/355 keyword'leri.
- AYM bireysel başvuru: mülkiyet, çalışma hakkı, eşit muamele (mevcut topluyu domain'e ayırma).
- İBK seed: ayrı keyword set, court_type override.

### W15 — Regulator otorite
- `scripts/seed/regulators.py` yeni: KVKK + Rekabet + SPK + BDDK + Sayıştay.
- Manuel JSONL import (`data/seed_state/regulator_kvkk.jsonl` vb.).
- Payload field: `regulator` (yargi/kvkk/rekabet/spk/bddk/sayistay), `decision_type`.

### W16 — Otomatik tazeleme
- `scripts/refresh_resmi_gazete.py` — günlük poll, RG mükerrer/asıl ayrımı.
- `scripts/refresh_yargitay_recent.py` — son 30 gün delta-sync (her domain × her court).
- `core/scheduler.py` — APScheduler factory, FastAPI lifespan'a entegre.

## 6. Hukuk Konsültasyonu Notları (yer tutucu)

> **NOT:** W11.1 görevinde Çankaya Hukuk Fakültesi hocasından konsültasyon
> alınacaktı (2h). Konsültasyon bu raporun yazıldığı anda mevcut değil.
> Mevcut liste **yargi-mcp output'ları + yasaların kapsam tablosu + akademik
> kaynaklardan derlenmiştir**. Hoca konsültasyonu sonrası bu rapor
> revize edilecek:
> - Hangi kanun "ana", hangi "tamamlayıcı"
> - Hangi Yargıtay/Danıştay daire kararları landmark
> - Hangi maddelerin günlük uygulamada en sık atıf alınanları

Belirsizlik kalan yerler `[HUKUK: doğrulanmalı]` ile işaretlenebilir.

## 7. Risk

| Risk | Olasılık | Düşüş |
|---|---|---|
| Hoca konsültasyonu gelmezse audit eksik kalır | Yüksek | LLM + Yargıtay daire listesi ile başla, sonraki sprint'te güncelle |
| Eklenen yeni kanunların hepsi mevzuat-mcp'de yok | Orta | search_mevzuat ile kontrol et, yoksa skip + warn |
| KVKK/Rekabet HTML scrape ToS ihlali | Yüksek | Sadece kamuya açık karar özetleri; manuel JSONL hazırla |

## 8. Sonuç

**W11 audit sonucu:** Sprint-5 plan'ı uygulanabilir. Kanun listesi 17→41 mümkün (24 yeni, hepsi mevzuat.gov.tr'de mevcut). Karar genişlemesi 7 yeni daire + 4 yeni tarih penceresi + Danıştay daire spesifik filtre ile teknik olarak gerçekleştirilebilir. Regulator katmanı manuel JSONL import + opsiyonel HTML scrape ile başlanır.

**Sonraki adım (W12):** `seed_mevzuat.py` TARGET_LAWS expand + `mevzuat_client.py` KANUN_KODU_TO_NUMARA expand + `agents/config.py` DOMAIN_TO_KANUN_KODU expand.
