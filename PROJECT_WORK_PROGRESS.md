# IMS Performance Manager — Kanonik Çalışma / Devir Kaydı

> Son güncelleme: **24 Ağustos 2026 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Bu dosya PC Codex, mobil ChatGPT ve sonraki çalışma oturumları için **tek güncel checkpoint** olarak kullanılmalıdır.

---

# 1. AKTİF DURUM — BURADAN DEVAM ET

## GitHub / production main

- Güncel `main`: **`783a000389c08408e36376f93b9355371c31b569`**
- Bu SHA PR **#145 — Recycle heavy IMS upload worker after response** merge commitidir.
- Production host: `130.162.48.162:8000`
- Service: `ims-performance-manager.service`
- Oracle Cloud Frankfurt; yaklaşık 2 CPU / 1 GB RAM / 2 GB swap.
- SQLite WAL + busy_timeout=30000 korunuyor.

### Çok önemli: #145 kodu henüz canlı service'e geçirilmedi

`main` merge oldu fakat production workflow **Issue #146** ile güvenlik kapısında FAIL etti.

- Workflow: `32755810634`
- Issue: **#146 — IMS production deployment FAILED**
- Failure service restarttan **önce**, representative performance gate'te oluştu.
- Bu nedenle Gunicorn post-IMS worker recycle fix'i henüz çalışan production processlerine yüklenmedi.
- Mevcut production service, kullanıcının manuel restartı sonrası hızlı çalışan önceki runtime ile devam ediyor.

## Şu an açık çalışma

Branch: **`agent/representative-market-query-memoization`**

Amaç:

1. Issue #146'da Şubat döneminde ortaya çıkan `31 SELECT > 30` performance-gate failure'ını gerçek sorgu tekrarlarını kaldırarak düzeltmek.
2. Eşiği yükseltmemek; aynı current upload ID ve brick-scope sorgularını tek market build içinde tekrar tekrar çağırmamak.
3. PR #145 worker recycle fix'inin acceptance sonrası gerçekten production'a geçmesini sağlamak.
4. `PROJECT_WORK_PROGRESS.md` güncellemelerinin tek başına gereksiz production deploy tetiklemesini önlemek.

Uygulanan query optimizasyonu:

- `RepresentativeMarketService` optimizer içinde current/previous `(year, month) -> latest upload id` yalnız **service instance/build** boyunca memoize edilir.
- Aynı `(year, month) -> brick/fallback scope` yalnız **service instance/build** boyunca memoize edilir.
- Global/process cache değildir; requestler arasında stale veri taşımaz.
- `build()` başında request-local memo sıfırlanır.
- aggregate competition / raw brick / exact brick competition aynı aktif upload ve brick scope'u tekrar SELECT etmez.
- Business data veya hesap semantiği değişmez.

Yeni regresyon testi:

`tests/test_representative_market_query_memoization.py`

- market read path'leri art arda çalıştırılır;
- aynı current-period `ims_uploads` SELECT'i **1** kez;
- aynı brick-scope `representative_brick_assignments` SELECT'i **1** kez çalışmak zorundadır.

Deploy workflow değişikliği:

- `pull_request -> main` CI davranışı aynen korunur.
- `push -> main` içinde yalnız `PROJECT_WORK_PROGRESS.md` değişen push için `paths-ignore` eklendi.
- Böylece kod PR'ları full CI + production deploy akışından geçmeye devam eder.
- Gelecekte checkpoint dosyasını güncellemek tek başına gereksiz server deploy/restart oluşturmaz.

---

# 2. 24 AĞUSTOS 2026 — ŞUBAT 6. HAFTA PERFORMANS OLAYI

Şubat **6. hafta IMS** yüklendikten sonra:

- login sonrası `/dashboard/` server-side yanıtı yaklaşık **11 saniyeye** çıktı;
- sayfalar genel olarak ağırlaştı;
- loglarda 500/traceback yerine uzun request süreleri görüldü;
- IMS importu aynı Gunicorn web worker içinde pandas/openpyxl ile çalışıyor;
- worker normalde `max_requests=1000` olana kadar yaşadığı için küçük ~1 GB hostta import sonrası retained heap + swap baskısı oluşabildi.

Kullanıcı production'da manuel:

```bash
sudo systemctl restart ims-performance-manager.service
ims-kontrol
```

çalıştırdı.

Sonuç:

- otomatik başlatma: `enabled`
- çalışma durumu: `active`
- dashboard tekrar **1 saniyeden daha hızlı** açılmaya başladı.

Bu canlı A/B gözlemi, ana yavaşlığın veri hacminin kalıcı DB sorgu maliyetinden değil import sonrası worker memory/swap pressure'dan kaynaklandığını güçlü biçimde doğruladı.

---

# 3. PR #145 — WORKER RECYCLE FIX

PR #145 merge SHA:

`783a000389c08408e36376f93b9355371c31b569`

Gunicorn `post_request` hook:

- yalnız `POST /ims/upload` isteğini işleyen worker response tamamlandıktan sonra graceful recycle edilir;
- diğer worker hizmet vermeye devam eder;
- import tamamlandıktan sonra pandas/openpyxl retained heap'i yeni worker process ile bırakılır;
- normal dashboard/login requestleri worker recycle etmez.

PR #145 final CI:

- **307 collected**
- **305 passed**
- **2 skipped**
- **0 failed**
- 50-upload / 5,000,000 competition-row scale probe PASS.

İlk PR CI'de PC Codex döneminden kalmış eski production-upload testi `PENDING_VALIDATION` beklediği için failure vermişti. Güncel route artık request içinde production workbook'u doğrular; invalid source `FAILED` olur. Eski assertion açıkça superseded olarak işaretlendi ve güncel contract için `test_invalid_production_upload_fails_without_mutating_ims` eklendi. Bu test invalid production workbook'un `FAILED/Hatalı` olduğunu ve IMS tablolarını değiştirmediğini doğrular.

---

# 4. ISSUE #146 PRODUCTION GATE EVIDENCE

Commit:

`783a000389c08408e36376f93b9355371c31b569`

Workflow:

`32755810634`

SQLite / capacity:

- journal mode: WAL
- busy_timeout: 30000
- integrity: OK
- active DB: **250,650,624 bytes**
- disk free: **36,689,305,600 bytes**
- +49 IMS estimated active growth: **3,307,748,307 bytes**
- capacity result: **PASS**
- all bounded query plans/indexes: PASS

Current row counts at #146:

- `ims_competition_data`: **386,300**
- `ims_facts`: **10,472**
- `ims_raw_data`: **97,353**
- `ims_summary`: **1,582**
- `ims_uploads`: **4**
- `targets`: **1,582**

Representative performance at 2026/02:

- cold max/p95: **0.6239 s**
- warm max/p95: **0.1815 s**
- max competition SELECT: **4 / threshold 4**
- unscoped competition SELECT: **0**
- max total SELECT: **31 / threshold 30 → FAIL**

Yani gerçek latency iyi; failure yalnız sorgu-budget regressiyonudur. Eşik yükseltilmeyecek. Tek build içindeki tekrar upload/scope sorguları memoize edilerek yeniden <=30 hedefleniyor.

---

# 5. KULLANICININ AKTİF IMS ÇALIŞMA PLANI

- Ocak IMS yüklemeleri tamamlandı.
- Şubat IMS yüklemelerine geçildi.
- 6. hafta Şubat IMS production DB'ye yüklendi.
- Tüm IMS dosyaları tamamlanana kadar Türkiye Pazar Analizi final olarak kurulmayacak.
- Tüm IMS tarihçesi yüklendikten sonra Türkiye Pazar Analizi toplu üretilecek.
- Analiz hedef kırılımları: Türkiye → bölge → il → brick; ürün grubu → rakip ürün; aylık / 3 aylık / 6 aylık / yıllık.
- Gerçek `0` data olarak korunacak; eksik veri sıfır diye uydurulmayacak.

---

# 6. PC CODEX İLE 23–24 AĞUSTOS'TA GELEN ÖNEMLİ İLERLEMELER

- 1. ve 2. üretim Excel entegrasyonu kuruldu.
- Production TL/kutu hedef ve gerçekleşmeleri kaynak olarak ayrı saklanıyor.
- Source priority değişmedi: **P2 > P1 > IMS**.
- Product-level fallback korunuyor: P2'de ürün yoksa P1; P1'de yoksa IMS.
- Prim simülasyonu DB'ye simülasyon yazmadan geçici/canlı çalışacak şekilde güçlendirildi.
- Prim yüzde basamak kuralı: ondalık ancak `,50`yi aşarsa yukarı basamağa geçer; ör. `%129,50` alt basamak, `%129,51` üst basamak.
- Bölgesel rakip/pazar merkezi: 11 bölge, ürün grubu, rakip ve il kırılımları.
- Rakip kapsamındaki eski ilk-5 sınırı kaldırıldı; kaynakta bulunan 29/29 rakip korunuyor.
- Bölgesel rakip yapısı şirket ürünü → rakip ürün → il analizi şeklinde ilerliyor.
- Ana dashboard'dan Bölge Pazar Payları Sıralaması ve Bölgesel Ürün Bazlı Rekabet Analizi kaldırıldı.
- AI Yönetici Özeti'nden Gelecek Ay Ciro Tahmini alanı kaldırıldı.
- Dashboard kutu hedef görünürlüğü/kontrastı güçlendirildi.

---

# 7. DEĞİŞTİRİLMEYECEK BUSINESS KURALLARI

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

# 8. BOS / BOŞ / VACANCY KURALLARI

- `BOS != BOŞ`.
- `DİYARBAKIR BOS != DİYARBAKIR BOŞ`; ayrı stable Representative ID.
- `BOS KADRO` / `BOŞ KADRO` slot identity korunur.
- `BOSTANCI` vacancy değildir.
- `BRICK` tek başına vacancy identity değildir.
- Deterministik tek eşleşme yoksa tahmin yapılmaz.
- Vacancy resolution başarısızsa accent-insensitive fuzzy fallback yapılmaz.
- Historic vacancy PK korunur; duplicate Representative oluşturulmaz.

---

# 9. IMS IMPORTER SÖZLEŞMESİ

Importer tek dosya adına, sheet sırasına veya sabit header satırına bağlı olmayacak.

- content/signature-first discovery;
- sheet adı yalnız yardımcı/fallback sinyali;
- header/kolon sırası sabit değil;
- temsilci / ürün / brick / bölge + TL / KUTU / PP / hedef / actual / realization semantiği;
- deterministik eşleşme varsa otomatik işle;
- belirsiz anlamda FAIL/REVIEW;
- `0` gerçek data, blank değildir;
- derived/master ilişkisi fiziksel hücre koordinatına değil semantik key'e dayanır.

---

# 10. SQLITE / UZUN DÖNEM DB KARARI

**Tek `ipm.db` ile devam et. Şimdilik yıllık SQLite shard oluşturma.**

- kritik read path'leri kompozit indeksli;
- +49 IMS production capacity gate halen PASS;
- yıllık DB shard cross-year query / migration / backup / routing karmaşıklığı getirir;
- ileride ücretli Oracle sunucuya geçilirse aynı DB daha güçlü CPU/RAM/storage üzerine taşınabilir;
- 5–10 yıl sonra gerçek concurrency/WAL/backup/latency sınırı oluşursa yıllık SQLite parçalamak yerine PostgreSQL migration değerlendirilecek.

Kaba uzun dönem büyüme:

- +49 IMS ≈ 3.3 GB aktif DB;
- 5 yıl ≈ 15–20 GB;
- 10 yıl ≈ 30–40 GB.

Bu büyüklükler tek başına SQLite limiti değildir; karar p95 latency, WAL contention, backup/integrity süresi, RAM ve disk baskısıyla verilir.

---

# 11. PERFORMANS MİLESTONE'LARI

## Temsilci ekranı

PR #130 / #132 / #135 sonrası production referansı:

- cold yaklaşık <0.5 s;
- warm yaklaşık <0.2 s;
- max competition SELECT ~3;
- max total SELECT ~28;
- unscoped competition SELECT 0.

Şubat 6. hafta sonrası Issue #146 latency halen iyi, fakat total query count 31'e çıktı; current branch bunun tekrarlarını kaldırıyor.

## SQLite scale

PR #141:

- WAL / busy_timeout korunuyor;
- connection cache / mmap / temp_store optimizasyonları;
- post-import `PRAGMA optimize` + `wal_checkpoint(PASSIVE)`;
- otomatik full VACUUM yok;
- +49 IMS capacity gate;
- synthetic 50-upload probe ~5M competition row seviyesinde bounded indexed queries PASS.

---

# 12. ORACLE ALTYAPI KARARI

Yeni Always Free Ampere A1 denendi:

- Frankfurt AD1/AD2/AD3 `VM.Standard.A1.Flex` → Out of capacity;
- 2 OCPU / 12 GB ve 1 OCPU / 6 GB denendi;
- mevcut IMS production VM silinmedi;
- ücretli shape'e geçilmedi.

Şimdilik mevcut Free production ile devam ediliyor. İleride A1 veya ücretli güçlü sunucu bulunursa migration paralel staging + acceptance ile yapılacak; eski production yeni makine tam PASS olmadan kapatılmayacak.

---

# 13. SONRAKİ ADIM

1. `agent/representative-market-query-memoization` için full CI çalıştır.
2. Yeni query memoization regression testi PASS olmalı.
3. 50-upload scale probe PASS olmalı.
4. Full CI green ise PR aç/merge et.
5. Main production workflow'da representative performance gate'in **<=30 total SELECT** olduğunu doğrula.
6. SQLite runtime/capacity/IMS acceptance/representative performance bütün gate'leri PASS olmadan service restart kabul etme.
7. Production SUCCESS evidence Issue oluşmalı ve `/login` health PASS olmalı.
8. Sonra worker recycle fix'inin artık canlı main/service içinde olduğunu doğrula.
9. `PROJECT_WORK_PROGRESS.md` dosyasını final merge SHA + workflow + Issue + query sayılarıyla güncelle. Progress-only main update artık deploy tetiklememeli.
10. Ardından Şubat IMS yüklemelerine devam et.
