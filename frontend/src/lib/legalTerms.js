/* ADALET hukuki terim sözlüğü — LegalTooltip bileşeni tarafından kullanılır.
   Anahtar: metinde aranacak terim (küçük harf). Değer: kısa açıklama.
   [DOĞRULA: hukuki açıklamalar Avukat danışmanlığıyla doğrulanmalı] */
export const LEGAL_TERMS = {
  // İş Hukuku
  "kıdem tazminatı": "Her tam çalışma yılı için 30 günlük brüt ücret üzerinden hesaplanır. Tavan brüt asgari ücretin 7,5 katıdır.",
  "ihbar tazminatı": "İş sözleşmesini fesheden tarafın, yasal bildirim süresine uymadan yapılan fesihlerde ödemekle yükümlü olduğu tazminattır.",
  "ihbar süresi": "Çalışma süresine göre değişen, iş sözleşmesinin feshinden önce verilmesi gereken bildirim süresi.",
  "işe iade davası": "Haksız fesih durumunda işçinin yeniden işe alınması için 1 ay içinde iş mahkemesine açılan dava.",
  // Tüketici Hukuku
  "ayıplı mal": "Amacına uygun olmayan, değer veya kullanımını etkileyen eksikliği bulunan ürün.",
  "cayma hakkı": "Mesafeli sözleşmelerde tüketicinin gerekçe göstermeden 14 gün içinde sözleşmeden dönme hakkı.",
  "tüketici hakem heyeti": "3.000 TL altı tüketici uyuşmazlıklarına bakan zorunlu başvuru mercii.",
  "garanti süresi": "Üreticinin veya satıcının malın ayıpsız çalışacağını taahhüt ettiği süre (asgari 2 yıl).",
  // Kira Hukuku
  "kira depozito": "En fazla 3 aylık kira bedeli kadar alınabilen ve kira sonunda iade edilmesi gereken güvence bedeli.",
  "tahliye davası": "Kiracının taşınmazdan çıkarılması için kiraya verenin açtığı dava.",
  "kira artışı": "Kira artış oranı; TÜİK 12 aylık TÜFE ortalamasını aşamaz (konut kiraları için yasal üst sınır).",
  // Genel Hukuk
  "zamanaşımı": "Hakkın kullanılabilmesi için tanınan azami yasal süre. Süre geçince hak, dava yoluyla talep edilemez.",
  "tebliğ": "Yasal bir belgenin yetkili makam aracılığıyla muhataba resmi yolla ulaştırılması.",
  "itiraz süresi": "Bir karara veya işleme karşı itiraz hakkının kullanılabileceği yasal süre.",
  "icra takibi": "Borcun ödenmemesi durumunda alacaklının icra müdürlüğü aracılığıyla tahsilat başlatması.",
  "hak düşürücü süre": "Geçirilmesi halinde hakkın tamamen ortadan kalktığı, uzatılamaz veya durdurulamaz yasal süre.",
  "vekalet": "Bir kişinin başkasını hukuki işlemler için temsil etmesine yetkili kılan belge.",
  "ihtarname": "Karşı tarafa bir hakkın kullanılacağını veya borcun ödenmesi gerektiğini bildiren resmi uyarı mektubu.",
  "islah": "Davada yapılmış usul işlemlerinin kısmen veya tamamen düzeltilmesi.",
  "temyiz": "Bölge adliye mahkemesi veya Yargıtay'a yapılan kanun yolu başvurusu.",
};

/** Metinde hukuki terimleri bul, ilk eşleşmeyi döndür.
 *  @param {string} text
 *  @returns {Array<{before:string, term:string, def:string, after:string}> | null}
 */
export function findLegalTerms(text) {
  if (!text) return null;
  const lower = text.toLowerCase();
  const hits = [];
  for (const [term, def] of Object.entries(LEGAL_TERMS)) {
    const idx = lower.indexOf(term);
    if (idx !== -1) hits.push({ idx, term, def, end: idx + term.length });
  }
  if (!hits.length) return null;
  // Çakışmaları filtrele (her pozisyonda sadece en uzun terimi al)
  hits.sort((a, b) => a.idx - b.idx || b.term.length - a.term.length);
  const result = [];
  let covered = 0;
  for (const h of hits) {
    if (h.idx < covered) continue; // iç içe geçmiş, atla
    result.push(h);
    covered = h.end;
  }
  return result.length ? result : null;
}
