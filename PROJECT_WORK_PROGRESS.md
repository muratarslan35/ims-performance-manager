# IMS Performance Manager — Kanonik Çalışma / Devir Kaydı

> Son güncelleme: **26 Ağustos 2026 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Bu dosya PC Codex, mobil ChatGPT ve sonraki çalışma oturumları için **tek güncel checkpoint** olarak kullanılmalıdır.

---

# 0. 26 AĞUSTOS 2026 — PC CODEX KESİN DEVAM NOKTASI

Bu bölüm aşağıdaki eski kayıtların üzerindedir; çelişki halinde bu bölüm esas alınır.

# IMS Performance Manager — PC Codex Devir Noktası

Tarih: 25 Ağustos 2026 (Europe/Istanbul)

## Git durumu

- Repo: `muratarslan35/ims-performance-manager`
- Güncel GitHub main: `9637f6877ed2a9fd5beaa390cccc140c62004b6d`
- Bu commit PR #206 merge sonucudur.
- Paket içindeki `ims-performance-manager-all.bundle` bütün branch/ref geçmişini içerir ve `git bundle verify` PASS olmuştur.

## Uygulanan son değişiklikler

- Rekabet importer tüm sheet kayıtlarını aynı anda RAM'de tutmak yerine sheet-bazlı işler.
- Duplicate lookup yalnız business key'in parçası olan mevcut normalized sheet ile sınırlıdır.
- Production restart öncesi CPU load, available RAM, swap, disk, inode, DB/WAL boyutu ve acceptance süresi fail-closed ölçülür.
- Business kuralları, atomik transaction, conflict davranışı ve P2 > P1 > IMS önceliği değiştirilmedi.

## Production kanıtı

- Workflow #475 / run `32874274592` full suite ve 50-upload scale probe PASS.
- İlk deploy denemesi production representative performance gate FAIL; restart olmadı.
- Failed-job rerun'da sunucu büyük ölçüde normale döndü:
  - 7/8 cold ölçüm yaklaşık 0.4–1.2 saniye;
  - ilk cold ölçüm 7.2739 saniye;
  - p95 mevcut küçük örneklem hesabında max ile aynı olduğu için 5 saniye eşiğini aştı;
  - max 8 saniye eşiği aşılmadı;
  - warm p95 yaklaşık 0.2971 saniye;
  - SELECT sayısı 26, competition SELECT 4, unscoped 0.
- Acceptance adımına geçilmedi; production service restart edilmedi.
- Issue #208 ve #209 kalıcı FAILED evidence içerir.

## Yerel test kanıtı

Temiz worktree güncel main'den oluşturuldu ve ayrı `.venv` içinde full suite çalıştırıldı:

- 326 passed
- 2 skipped
- 1 failed
- süre: 91.23 saniye

Tek hata:

`tests/test_sqlite_scale_guard.py::test_capacity_audit_projects_49_uploads_and_rejects_full_scans`

Bu testin ayrıntılı `result["blocking"]` alanını yazdırarak gerçek nedeni doğrula. Test sentetik WAL DB kuruyor; CI aynı committe PASS olduğu için PC ortamı/SQLite davranışı ayrıştırılmadan test veya gate gevşetilmemeli.

## PC'de geri yükleme

```bash
git clone ims-performance-manager-all.bundle ims-performance-manager
cd ims-performance-manager
git remote set-url origin https://github.com/muratarslan35/ims-performance-manager.git
git fetch origin --prune
git switch main
git merge --ff-only origin/main
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt pytest
APP_ENV=testing SECRET_KEY=local-test-secret DATABASE_URL=sqlite:////tmp/ims-local-full.db \
  .venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/sqlite_scale_probe.py \
  --uploads 50 --competition-per-upload 100000 \
  --raw-per-upload 28091 --facts-per-upload 3164 \
  --max-query-seconds 3.0
```

## Kesin devam sırası

1. Yerel tek scale-guard hatasının `blocking` nedenini kanıtla ve deterministik düzelt.
2. Production performance ölçümünde ilk-run host/cache etkisini ayrı warmup ölçümüyle ayır; threshold yükseltme.
3. Timeout/cancel sonrasında uzakta kalan acceptance süreçlerini güvenli biçimde tespit/temizle ve geçici acceptance DB retention ekle.
4. Yerel full suite PASS ve 50-upload scale PASS olmadan push/PR yapma.
5. GitHub full CI PASS olmadan merge etme.
6. Production acceptance + resource gate + health PASS olmadan restart/tamamlandı iddiası verme.
7. Sonuçta `PROJECT_WORK_PROGRESS.md` dosyasını güncelle.

## Değiştirilmeyecek kurallar

- P2 > P1 > IMS ve product-level fallback.
- Gerçek 0 korunur; blank ile karıştırılmaz.
- NATIONAL/region official aggregates kişi toplamıyla değiştirilmez.
- Official Brick Spread side-channel masterdır, FACT değildir.
- BOS != BOŞ; BOSTANCI vacancy değildir; ambiguity'de tahmin yoktur.
- SQLite WAL, busy_timeout=30000, single-writer ve user vault korunur.
- Acceptance fail olursa mevcut canlı snapshot korunur.

## Ek production rerun kanıtı

- Workflow #475 / run `32874274592`, failed-job rerun da FAIL oldu.
- Sunucu normale yaklaştı: 7/8 cold ölçüm 0.4–1.2 saniye, ilk ölçüm 7.2739 saniye, warm p95 0.2971 saniye.
- Query sınırları korundu: total SELECT 26, competition SELECT 4, unscoped 0.
- Cold max 8 saniye sınırını geçmedi; 8 örnekli percentile hesabı p95'i max seçtiği için 5 saniye p95 gate'i FAIL oldu.
- Acceptance, resource gate, restart ve health adımlarına geçilmedi. Issue #209 kalıcı evidence'tır.

## PC Codex için ek zorunlu işler

- `verify_representative_performance.py` ölçümünden önce sonuç dışı kontrollü warmup/telemetry ekle; performans eşiklerini yükseltme.
- Timeout/cancel sonrası kalan acceptance süreçlerini ve stale `/tmp/ims-acceptance-*.db*` dosyalarını güvenli bounded cleanup ile yönet.
- Yerel scale-guard failure için `result["blocking"]`, journal mode ve query plans kanıtını al; testi körlemesine değiştirme.

---


# 1. AKTİF DURUM — BURADAN DEVAM ET

## Production

- Canlı uygulama kod SHA: **`a7dce15960fefe383c525ec84d0b633a44fa5cb1`**
- Bu SHA PR **#149 — Accept compact IMS region subtotal rows** merge commitidir.
- Production workflow: **#409 / `32809117903`**
- Kalıcı deployment evidence: **Issue #150 — IMS production deployment SUCCESS**
- Production host: `130.162.48.162:8000`
- Service: `ims-performance-manager.service`
- Oracle Cloud Frankfurt; yaklaşık 2 CPU / 1 GB RAM / 2 GB swap.
- SQLite: WAL, `busy_timeout=30000`, integrity OK.
- Production `/login` health check: **PASS**.
- Acceptance sonrası gerçek systemd service restartı tamamlandı.
- Post-IMS upload Gunicorn worker recycle canlıdır.

> Bu dosyanın yalnız-dokümantasyon commit SHA'sı production kod SHA'sından farklı olabilir. `PROJECT_WORK_PROGRESS.md`-only main push'ları deploy workflow'da `paths-ignore` ile hariç tutulmuştur; checkpoint güncellemesi gereksiz production restart oluşturmaz.

## Şu an açık kritik blocker

**Yok.**

Şubat 7. hafta IMS dosyasının ilk upload denemesi fail-closed olarak yayınlanmadı; canlı 6. hafta verisi korunmuştur. PR #149 ile kök neden giderildi ve fix production'a başarıyla alındı. Kullanıcı aynı 7. hafta dosyasını IMS Merkezi'nden tekrar yükleyebilir.

---

# 2. 25 AĞUSTOS 2026 — ŞUBAT 7. HAFTA IMS IMPORT OLAYI

Kullanıcının yüklediği dosya:

`Tayfun 7.Hafta Şubat Brick Analizi_.xlsx`

İlk production upload sonucu:

- 2026 / Şubat / 7. hafta algılandı;
- workbook **15/15** sheet olarak okundu;
- kaynak/kayıt: **21,930 / 21,930**;
- canonical unresolved representative/product: **0**;
- invalid: **0**;
- conflict: **0**;
- fakat import doğrulama aşamasında rollback edildi ve yayınlanmadı;
- failed upload kaydı production `ims_uploads` içinde tutuldu;
- önceki güvenli 6. hafta snapshotı canlı kalmaya devam etti.

Manager-facing failure raporundaki `fact=0 / rekabet=0` kök neden değildi; exception sonrası atomik rollback'in sonucuydu. Import pipeline herhangi bir exception'da rollback edip FAILED kaydı persist eder; bu nedenle yarım veri canlıya çıkmadı.

## Dosya yapısı incelemesi

7. hafta workbook 15 sheet içeriyor:

1. `TTS ÇIKIŞLARI`
2. `1001 BRICK SATIS`
3. `BRICK REA.`
4. `BAKİYE`
5. `TTS HAFTALIK ÇIKIŞLARI`
6. `AYLIK REKABET TL`
7. `AYLIK REKABET KUTU`
8. `TTS Rekabet`
9. `TTS Rekabet PP`
10. `ŞUBAT`
11. `ŞUBAT KUTU`
12. `ŞUBAT TL`
13. `KUTU`
14. `TL`
15. `PAZAR`

Önceki IMS örneklerinde ayrıca `Satış Brick Yayılımı` bulunabiliyordu. 7. haftada bu side-channel master sheet'in olmaması blocker değildir; Official Brick Spread FACT/SUMMARY/prim domainine zorunlu kaynak değildir.

## Gerçek kök neden

IMS pivot exportunda **region subtotal satırının hücre yerleşimi değişti**.

Eski biçim örneği:

- `A = 101 ISTANBUL`
- `B = 101 ISTANBUL`

7. hafta yeni biçimi:

- `A = boş`
- `B = 101 ISTANBUL`

Temsilci satırlarında ise A sütunu bölgeyi taşımaya devam ediyor, örneğin:

- `A = 101 ISTANBUL`
- `B = ENGIN YAPAK`

Eski `official_aggregate_service._aggregate_key()` yalnız `A == B` biçimini official region subtotal olarak kabul ediyordu. Yeni pivot biçimindeki 11 bölge subtotalı bu nedenle atlanıyor, NATIONAL official toplamları mevcutken bölge official toplamları oluşmuyordu. Strict NATIONAL ↔ region reconciliation doğru biçimde FAIL verip bütün importu rollback ediyordu.

Bu problem haftanın kendisinden veya veri hacminden kaynaklanmıyordu; **kaynak Excel pivot subtotal format drift** problemiydi.

---

# 3. PR #149 — COMPACT REGION SUBTOTAL FIX

Branch:

`agent/week7-region-subtotal-import-fix`

PR:

**#149 — Accept compact IMS region subtotal rows**

Merge SHA:

`a7dce15960fefe383c525ec84d0b633a44fa5cb1`

Uygulanan genel çözüm:

- eski `A=region, B=same region` biçimi aynen desteklenir;
- yeni `A=blank, B=<3 haneli bölge kodu + bölge etiketi>` biçimi deterministik official region subtotal olarak tanınır;
- person rows yanlışlıkla subtotal yapılamaz çünkü person row'larında A sütunu bölge bağlamını taşır;
- dosya adı, hafta numarası veya Şubat'a özel hard-code eklenmedi;
- NATIONAL/region reconciliation tolerance/eşiği **gevşetilmedi**;
- official aggregate otoritesi korunur; kişi toplamı official subtotalın yerine geçirilmez.

Yeni regression testi:

`test_compact_region_subtotal_rows_are_preserved_and_reconciled`

Test, hem BAKİYE hem TTS HAFTALIK ÇIKIŞLARI için compact subtotal biçimini simüle eder ve:

- official target region subtotalını;
- official actual TL/kutu subtotalını;
- NATIONAL ↔ region reconciliation PASS sonucunu

zorunlu kılar.

## PR #149 CI

Workflow: **#408 / `32808953468`**

- **309 collected**
- **307 passed**
- **2 skipped**
- **0 failed**
- yeni compact subtotal regression testi PASS
- 50-upload SQLite scale probe PASS
- synthetic competition: **5,000,000** rows
- synthetic raw: **1,404,550** rows
- synthetic fact: **158,200** rows
- competition six-upload query: **0.0115 s**
- latest FACT query: **0.0015 s**
- raw brick query: **0.0001 s**
- integrity: OK.

---

# 4. PRODUCTION SUCCESS — ISSUE #150

Commit:

`a7dce15960fefe383c525ec84d0b633a44fa5cb1`

Workflow:

`32809117903`

Result: **SUCCESS**

## Production gates

- full test suite: PASS
- 50-upload scale probe: PASS
- SQLite journal mode: WAL
- busy_timeout: 30000
- integrity: OK
- projected +49 IMS storage: PASS
- blocking capacity issues: `[]`
- all required composite indexes present
- bounded query plans: PASS
- representative performance: PASS
- isolated IMS acceptance: PASS
- IMS acceptance extras: PASS
- systemd restart: completed
- `/login` production health: PASS
- backup retention: PASS.

## Representative performance — 2026/02

- max total SELECT: **26** (`threshold=30`)
- max competition SELECT: **4** (`threshold=4`)
- unscoped competition SELECT: **0**
- cold max/p95: **0.7937 s**
- warm max/p95: **0.2888 s**
- result: **PASS**.

## Capacity snapshot

- active DB: **250,654,720 bytes**
- disk free: **37,086,199,808 bytes**
- +49 IMS estimated active DB growth: **3,307,748,307 bytes**
- storage projection: **PASS**
- production row counts before week7 retry:
  - `ims_competition_data`: **386,300**
  - `ims_facts`: **10,472**
  - `ims_raw_data`: **97,353**
  - `ims_summary`: **1,582**
  - `ims_uploads`: **5** (includes failed week7 attempt)
  - `targets`: **1,582**
- latest successful business upload remains upload id **4 / Şubat 6. hafta** until week7 is retried successfully.

Production acceptance baseline remained the safe completed workbook:

`Tayfun-1_6.Hafta_Subat_Brick_Analizi_.xlsx`

- 16/16 sheets verified
- source/stored: 28,098 / 28,098
- competition: 99,756
- fact: 3,164
- summary: 791
- target: 791
- official aggregates: 168
- representatives: 113
- regions: 11
- products: 7
- vacancies: 11
- unresolved/invalid/conflict: 0
- NATIONAL/region consistency: PASS.

Yeni rollback stamp: `20260825-043109`; retained IPM/users backup integrity OK.

---

# 5. 24 AĞUSTOS 2026 — ŞUBAT 6. HAFTA PERFORMANS OLAYI

6. hafta IMS yüklemesinden sonra login→dashboard server-side süre yaklaşık 11 saniyeye çıkmıştı. Manuel service restart sonrası dashboard yeniden 1 saniyeden hızlı açıldı. Bu A/B gözlemi import sonrası Gunicorn worker retained heap/swap baskısını doğruladı.

## PR #145 — worker recycle

Merge SHA:

`783a000389c08408e36376f93b9355371c31b569`

- yalnız `POST /ims/upload` isteğini işleyen Gunicorn worker response tamamlandıktan sonra graceful recycle edilir;
- diğer worker hizmet vermeye devam eder;
- pandas/openpyxl import heap'i sonraki dashboard/login isteklerine taşınmaz;
- normal requestler recycle edilmez;
- DB transaction, WAL, import lock ve business semantics değişmez.

Bu koruma production'da aktiftir; her IMS uploadundan sonra manuel service restart normalde gerekmemelidir.

## PR #147 — representative market query memoization

Merge SHA:

`73c64343f5555db5087b7a4120e64018c2ffeb0a`

- current upload ID aynı market build içinde bir kez okunur;
- representative brick scope aynı build içinde bir kez okunur;
- cache request/service-instance localdır; global stale cache değildir;
- performance threshold yükseltilmedi;
- redundant query kaldırılarak Şubat production max SELECT **31 → 26** düşürüldü.

Issue #148 production SUCCESS ile bu performans katmanı doğrulandı.

---

# 6. KULLANICININ AKTİF IMS ÇALIŞMA PLANI

- Ocak IMS yüklemeleri tamamlandı.
- Şubat IMS yüklemeleri devam ediyor.
- 6. hafta Şubat IMS production DB'de doğrulanmış son başarılı snapshot.
- 7. hafta ilk deneme fail-closed oldu; **PR #149 fix'i canlıya alındı ve aynı dosya şimdi yeniden yüklenmeli**.
- Sonraki Şubat IMS dosyaları sırayla yüklenecek.
- Tüm IMS dosyaları tamamlanana kadar final Türkiye Pazar Analizi oluşturulmayacak.
- Tüm IMS tarihçesi yüklendikten sonra Türkiye Pazar Analizi bütün dönemleri kullanarak toplu üretilecek.
- Hedef kırılımlar: Türkiye → bölge → il → brick; ürün grubu → rakip ürün; aylık / 3 aylık / 6 aylık / yıllık.
- Gerçek `0` data olarak korunacak; eksik veri sıfır diye uydurulmayacak.

---

# 7. PC CODEX İLE GELEN ÖNEMLİ İLERLEMELER

- 1. ve 2. üretim Excel entegrasyonu kuruldu.
- Production TL/kutu hedef ve gerçekleşmeleri kaynak olarak ayrı saklanıyor.
- Source priority: **P2 > P1 > IMS**.
- Product-level fallback: P2'de ürün yoksa P1; P1'de yoksa IMS.
- Prim simülasyonu DB'ye simülasyon yazmadan geçici/canlı çalışıyor.
- Prim yüzde basamak kuralı: ondalık ancak `,50`yi aşarsa yukarı basamağa geçer; `%129,50` alt, `%129,51` üst basamak.
- Bölgesel rakip/pazar merkezi: 11 bölge, ürün grubu, rakip ve il kırılımları.
- Rakip kapsamındaki eski ilk-5 sınırı kaldırıldı; kaynakta bulunan 29/29 rakip korunuyor.
- Bölgesel rakip yapısı şirket ürünü → rakip ürün → il analizi.
- Ana dashboard'dan Bölge Pazar Payları Sıralaması ve Bölgesel Ürün Bazlı Rekabet Analizi kaldırıldı.
- AI Yönetici Özeti'nden Gelecek Ay Ciro Tahmini kaldırıldı.
- Dashboard kutu hedef görünürlüğü/kontrastı güçlendirildi.

---

# 8. DEĞİŞTİRİLMEYECEK BUSINESS KURALLARI

- Production satış kaynağı: **P2 > P1 > IMS**.
- P1 geldiğinde IMS'in yerini hemen alır; P2 geldiğinde P1'in yerini alır.
- P2, P1 hiç gelmemiş olsa da final kaynak olabilir.
- Product-level fallback: P2 → P1 → IMS.
- Kaynak yoksa error; sahte `0` üretme.
- Nationwide snapshot farklı source tiplerini karıştırmaz.
- Production realizasyonu `%100` üzerinde kırpılmaz.
- Decimal precision korunur.
- Prime payout / entitlement / threshold davranışı redesign edilmez.
- Hedef business source/schema keyfi değiştirilmez.
- Official NATIONAL/region aggregate kişi toplamıyla ikame edilmez.
- Official Brick Spread FACT/SUMMARY/prim domainine karıştırılmaz; side-channel master kalır.
- Ana SQLite DB WAL modunda kalır.
- User vault `instance/persistent/users.db` bağımsız korunur.
- Validation failure durumunda yarım IMS publish edilmez.
- Acceptance isolated DB copy üzerinde çalışır.
- Full CI + production acceptance PASS olmadan restart yapılmaz.

---

# 9. BOS / BOŞ / VACANCY KURALLARI

- `BOS != BOŞ`.
- `DİYARBAKIR BOS != DİYARBAKIR BOŞ`; ayrı stable Representative ID.
- `BOS KADRO` / `BOŞ KADRO` slot identity korunur.
- `BOSTANCI` vacancy değildir.
- `BRICK` tek başına vacancy identity değildir.
- Deterministik tek eşleşme yoksa tahmin yapılmaz.
- Vacancy resolution başarısızsa accent-insensitive fuzzy fallback yapılmaz.
- Historic vacancy PK korunur; duplicate Representative oluşturulmaz.

---

# 10. IMS IMPORTER SÖZLEŞMESİ

Importer tek dosya adına, sheet sırasına veya sabit header satırına bağlı olmayacak.

- content/signature-first discovery;
- sheet adı yalnız yardımcı/fallback sinyali;
- header/kolon sırası sabit değil;
- pivot subtotal hücre konumu değişebilir; deterministik semantik kimlik varsa tanınmalıdır;
- temsilci / ürün / brick / bölge + TL / KUTU / PP / hedef / actual / realization semantiği;
- deterministik eşleşme varsa otomatik işle;
- belirsiz anlamda FAIL/REVIEW;
- `0` gerçek data, blank değildir;
- derived/master ilişkisi fiziksel hücre koordinatına değil semantik key'e dayanır.

---

# 11. SQLITE / UZUN DÖNEM DB KARARI

**Tek `ipm.db` ile devam et. Şimdilik yıllık SQLite shard oluşturma.**

- kritik read path'leri kompozit indeksli;
- +49 IMS production capacity gate PASS;
- yıllık DB shard cross-year query/migration/backup/routing karmaşıklığı getirir;
- ileride ücretli Oracle sunucuya geçilirse aynı DB daha güçlü CPU/RAM/storage'a taşınabilir;
- gerçek concurrency/WAL/backup/latency sınırı oluşursa yıllık SQLite parçalamak yerine PostgreSQL migration değerlendirilecek.

Kaba büyüme:

- +49 IMS ≈ 3.3 GB aktif DB;
- 5 yıl ≈ 15–20 GB;
- 10 yıl ≈ 30–40 GB.

Karar p95 latency, WAL contention, backup/integrity süresi, RAM ve disk baskısıyla verilecek.

---

# 12. ORACLE ALTYAPI KARARI

Always Free Ampere A1 Frankfurt AD1/AD2/AD3 denendi ve kapasite bulunamadı. Mevcut IMS production VM silinmedi, ücretli shape'e geçilmedi. Şimdilik mevcut Free production ile devam ediliyor. Yeni makineye geçiş gerekirse paralel staging + acceptance olmadan eski production kapatılmayacak.

---

# 13. SONRAKİ ADIM

1. Kullanıcı **aynı Şubat 7. hafta IMS dosyasını yeniden yüklesin**.
2. Başarılı reportta özellikle 15/15 sheet, source/stored, non-zero FACT/competition, 11 region official reconciliation ve zero/unresolved/invalid/conflict sonuçları kontrol edilsin.
3. Upload sonrası worker recycle nedeniyle dashboard genel performansı tekrar gözlensin; manuel restart normalde gerekmez.
4. Yeni IMS'de manager report warning çıkarsa tahminle kabul etme; blocker'ı kaynak semantiğinden çöz.
5. Önemli her kod/veri/deploy değişikliğinde bu `PROJECT_WORK_PROGRESS.md` dosyasını güncelle.
6. Tüm IMS tarihçesi tamamlanınca bütün dönemleri kullanan Türkiye Pazar Analizi'ni topluca tasarla ve kur.
