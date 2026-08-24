# IMS Performance Manager — Kanonik Çalışma / Devir Kaydı

> Son güncelleme: **24 Ağustos 2026 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Bu dosya PC Codex, mobil ChatGPT ve sonraki çalışma oturumları için **tek güncel checkpoint** olarak kullanılmalıdır.

---

# 1. AKTİF DURUM — BURADAN DEVAM ET

## Production main

- Güncel doğrulanmış `main`: `12d0c02430093ca43fe14b5d5b1d0f471684fe56`
- Son checkpoint commit mesajı: `Document dashboard simplification checkpoint`
- Uygulama production'da `130.162.48.162:8000` üzerinde çalışıyor.
- Service: `ims-performance-manager.service`
- Host: Oracle Cloud Frankfurt, yaklaşık 2 CPU / 1 GB RAM / 2 GB swap.
- SQLite WAL + busy_timeout=30000 korunuyor.

## Şu an açık çalışma

PR **#145 — Recycle heavy IMS upload worker after response**

- Branch: `agent/recycle-worker-after-ims-import`
- Amaç: büyük IMS workbook importundan sonra pandas/openpyxl nedeniyle Gunicorn worker processinde kalan heap/RAM/swap baskısını temizlemek.
- Runtime değişikliği yalnız `/ims/upload` POST isteğini işleyen worker'a uygulanır.
- Gunicorn `post_request` hook response gönderildikten sonra o worker'ı graceful recycle eder.
- Diğer worker hizmet vermeye devam eder.
- DB transaction, import lock, SQLite WAL, parser, hedef, prim veya P2>P1>IMS business semantiği değiştirilmez.

## 24 Ağustos 2026 performans olayı

Şubat **6. hafta IMS** yüklendikten sonra:

- login sonrası `/dashboard/` server-side yanıtı yaklaşık **11 saniyeye** çıktı;
- sayfalar genel olarak ağırlaştı;
- loglarda 500/traceback yerine uzun request süreleri görüldü;
- IMS importu aynı Gunicorn web worker içinde pandas/openpyxl ile çalışıyor;
- current worker normalde `max_requests=1000` olana kadar yaşayabildiği için küçük ~1 GB hostta import sonrası retained heap + swap baskısı oluşabiliyor.

Canlıda manuel:

`sudo systemctl restart ims-performance-manager.service`

uygulandı.

Sonuç:

- `ims-kontrol`: enabled / active;
- dashboard tekrar **1 saniyeden daha hızlı** açılmaya başladı.

Bu gözlem veri hacminin veya Şubat DB kayıtlarının kalıcı sorgu yavaşlığı yaratmadığını; ana problemin import sonrası worker memory pressure olduğunu güçlü biçimde doğruladı.

## PR #145 CI durumu

İlk CI run `32753628240`:

- 306 collected
- 304 passed
- 1 skipped
- 1 failed

Yeni Gunicorn worker-recycle testlerinin ikisi de PASS oldu.

Tek failure yeni runtime kodundan değil, PC Codex'teki production upload değişikliğinden önce kalmış eski testti:

`test_production_upload_is_staged_without_changing_ims_data`

Eski test `PENDING_VALIDATION` bekliyordu; güncel route production workbook'u request içinde doğruluyor ve geçersiz workbook'u `FAILED` yapıyor.

Bu nedenle:

- eski pending-state assertion açıkça superseded olarak işaretlendi;
- `test_invalid_production_upload_fails_without_mutating_ims` integration testi eklendi;
- yeni test geçersiz production workbook'un `FAILED/Hatalı` olduğunu ve IMSUpload / IMSRawData / IMSFact / IMSSummary tablolarını değiştirmediğini doğrular.

Güncel CI run: **`32755378144` / run #402** — bu checkpoint yazılırken çalışıyor.

**Full CI yeşil olmadan merge yok. Production acceptance PASS olmadan deploy/restart yok.**

---

# 2. KULLANICININ AKTİF ÇALIŞMA PLANI

- Ocak IMS yüklemeleri tamamlandı.
- Şubat IMS yüklemelerine geçildi.
- Tüm IMS dosyaları tamamlanana kadar Türkiye Pazar Analizi final olarak kurulmayacak.
- Tüm IMS tarihçesi yüklendikten sonra Türkiye Pazar Analizi toplu üretilecek.
- Analiz hedef kırılımları: Türkiye → bölge → il → brick; ürün grubu → rakip ürün; aylık / 3 aylık / 6 aylık / yıllık.
- Gerçek `0` data olarak korunacak; eksik veri sıfır diye uydurulmayacak.

---

# 3. PC CODEX İLE 23–24 AĞUSTOS'TA GELEN ÖNEMLİ İLERLEMELER

- 1. ve 2. üretim Excel entegrasyonu kuruldu.
- Production TL/kutu hedef ve gerçekleşmeleri kaynak olarak ayrı saklanıyor.
- Source priority değişmedi: **P2 > P1 > IMS**.
- Product-level fallback korunuyor: P2'de ürün yoksa P1; P1'de yoksa IMS.
- Prim simülasyonu DB'ye simülasyon yazmadan geçici/canlı çalışacak şekilde güçlendirildi.
- Prim yüzde basamak kuralı: ondalık ancak `,50`yi aşarsa yukarı basamağa geçer; ör. %129,50 alt basamak, %129,51 üst basamak.
- Bölgesel rakip/pazar merkezi: 11 bölge, ürün grubu, rakip ve il kırılımları.
- Rakip kapsamındaki eski ilk-5 sınırı kaldırıldı; kaynakta bulunan 29/29 rakip korunuyor.
- Bölgesel rakip yapısı şirket ürünü → rakip ürün → il analizi şeklinde ilerliyor.
- Ana dashboard'dan Bölge Pazar Payları Sıralaması ve Bölgesel Ürün Bazlı Rekabet Analizi kaldırıldı.
- AI Yönetici Özeti'nden Gelecek Ay Ciro Tahmini alanı kaldırıldı.
- Dashboard kutu hedef görünürlüğü/kontrastı güçlendirildi.

---

# 4. DEĞİŞTİRİLMEYECEK BUSINESS KURALLARI

- Production satış kaynağı önceliği: **P2 > P1 > IMS**.
- P1 geldiğinde IMS beklenmez; P1 IMS'in yerini hemen alır.
- P2 geldiğinde P1'in yerini alır.
- P2, P1 hiç gelmemiş olsa da final kaynak olabilir.
- Product-level fallback: P2'de ürün yoksa P1; P1'de de yoksa IMS.
- Kaynak yoksa error; sahte `0` üretme.
- Nationwide snapshot farklı source tiplerini karıştırmaz.
- Production realizasyonu `%100` üzerinde kırpılmaz.
- Decimal precision korunur.
- Prime engine payout / entitlement / threshold davranışı redesign edilmez.
- Hedef business source/schema keyfi değiştirilmez.
- Official NATIONAL/region aggregate kişi toplamıyla ikame edilmez.
- Official Brick Spread FACT/SUMMARY/prim domainine karıştırılmaz; side-channel master olarak kalır.
- Ana SQLite DB WAL modunda kalır.
- User vault `instance/persistent/users.db` bağımsız korunur.
- Validation failure durumunda yarım IMS publish edilmez.
- Acceptance isolated DB copy üzerinde çalışır.
- Full CI + production acceptance PASS olmadan deploy/restart yapılmaz.

---

# 5. BOS / BOŞ / VACANCY KURALLARI

- `BOS != BOŞ`.
- `DİYARBAKIR BOS != DİYARBAKIR BOŞ`; ayrı stable Representative ID.
- `BOS KADRO` / `BOŞ KADRO` slot identity korunur.
- `BOSTANCI` vacancy değildir.
- `BRICK` tek başına vacancy identity değildir.
- Deterministik tek eşleşme yoksa tahmin yapılmaz.
- Vacancy resolution başarısızsa accent-insensitive fuzzy fallback yapılmaz.
- Historic vacancy PK korunur; duplicate Representative oluşturulmaz.

---

# 6. IMS IMPORTER SÖZLEŞMESİ

Importer tek dosya adına, sheet sırasına veya sabit header satırına bağlı olmayacak.

Korunacak yaklaşım:

- content/signature-first discovery;
- sheet adı yalnız yardımcı/fallback sinyali;
- header/kolon sırası sabit değil;
- temsilci / ürün / brick / bölge + TL / KUTU / PP / hedef / actual / realization semantiği;
- deterministik eşleşme varsa otomatik işle;
- belirsiz anlamda FAIL/REVIEW;
- `0` gerçek data, blank değildir;
- derived/master ilişkisi fiziksel hücre koordinatına değil semantik key'e dayanır.

---

# 7. SQLITE / UZUN DÖNEM DB KARARI

**Tek `ipm.db` ile devam et. Şimdilik yıllık SQLite shard oluşturma.**

Gerekçe:

- kritik read path'leri kompozit indeksli;
- +49 IMS production capacity gate PASS olmuş durumda;
- yıllık DB shard cross-year query / migration / backup / routing karmaşıklığı getirir;
- ileride ücretli Oracle sunucuya geçilirse aynı DB daha güçlü CPU/RAM/storage üzerine taşınabilir;
- 5–10 yıl sonra gerçek concurrency/WAL/backup/latency sınırı oluşursa yıllık SQLite parçalamak yerine PostgreSQL migration değerlendirilecek.

Production projeksiyonu yaklaşık:

- +49 IMS → +3.15 GB aktif DB;
- 5 yıl kaba ~15–20 GB;
- 10 yıl kaba ~30–40 GB.

Bu büyüklükler tek başına SQLite limiti değildir; gerçek karar p95 latency, WAL contention, backup/integrity süresi, RAM ve disk baskısıyla verilir.

---

# 8. PERFORMANS MİLESTONE'LARI

## Temsilci ekranı

Eski 25–30 saniyelik temsilci detail problemi giderildi.

PR #130 / #132 / #135 sonrası production referansı:

- cold yaklaşık <0.5 s;
- warm yaklaşık <0.2 s;
- max competition SELECT ~3;
- max total SELECT ~28;
- unscoped competition SELECT 0.

## SQLite scale

PR #141:

- WAL / busy_timeout korunuyor;
- connection cache / mmap / temp_store optimizasyonları;
- post-import `PRAGMA optimize` + `wal_checkpoint(PASSIVE)`;
- otomatik full VACUUM yok;
- +49 IMS capacity gate;
- synthetic 50-upload probe ~5M competition row seviyesinde bounded indexed queries PASS.

---

# 9. ORACLE ALTYAPI KARARI

Yeni Always Free Ampere A1 denendi:

- Frankfurt AD1/AD2/AD3 `VM.Standard.A1.Flex` → Out of capacity;
- 2 OCPU / 12 GB ve daha küçük 1 OCPU / 6 GB denendi;
- mevcut IMS production VM silinmedi;
- ücretli shape'e geçilmedi.

Şimdilik mevcut Free production ile devam ediliyor. İleride A1 veya ücretli güçlü sunucu bulunursa migration paralel staging + acceptance ile yapılacak; eski production yeni makine tam PASS olmadan kapatılmayacak.

---

# 10. SONRAKİ ADIM

1. CI run `32755378144` sonucunu doğrula.
2. Full suite green ise PR #145'i merge et.
3. Main production workflow'un acceptance ve deploy adımlarını izle.
4. Runtime / capacity / IMS acceptance / representative performance gate'leri PASS olmadan service restart kabul etme.
5. Production health ve worker recycle davranışını doğrula.
6. Bu dosyayı merge SHA + production workflow/issue evidence + final test sayılarıyla tekrar güncelle.
7. Ardından Şubat IMS yüklemelerine devam et.
