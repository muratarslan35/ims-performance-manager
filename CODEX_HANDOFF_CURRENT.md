# IMS Performance Manager — Codex Güncel Devir Dosyası

> Tarih: **26 Ağustos 2026 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Bu dosya, PC Codex ile devam ederken **en güncel durum için önce okunmalıdır**.  
> Tarihsel ayrıntılar ve eski checkpointler için ayrıca `PROJECT_WORK_PROGRESS.md` okunmalıdır.  
> Çelişki halinde bu dosyadaki son durum esas alınır.

---

# 1. GÜNCEL MAIN / DEPLOY DURUMU

- Güncel main merge SHA: **`7786fab25716f241f294cc739731aa2ce74672ad`**.
- Bu SHA, PR **#220 — Add isolated production IMS import benchmark** merge sonucudur.
- PR #220 öncesindeki kritik importer düzeltmesi PR **#218** ile merge edilmiştir.
- PR #218 sonrasında semantic official aggregate identity düzeltmesi production'a başarıyla deploy edilmiştir.
- PR #220 sonrasında production deploy workflow **#493 / run `33009859122`** SUCCESS tamamlanmıştır.
- Full test suite PASS.
- 50-upload SQLite scale probe PASS.
- Production deploy + verify SUCCESS.
- Production host: `130.162.48.162`.
- Service: `ims-performance-manager.service`.
- SQLite: WAL + `busy_timeout=30000`; integrity gate korunur.
- Business kuralları, P2 > P1 > IMS, prim/target mantığı ve fail-closed publish davranışı değiştirilmemiştir.

---

# 2. 7. HAFTA IMS DOSYASI

Gerçek dosya:

`Tayfun_7.Hafta_Subat_Brick_Analizi_.xlsx`

Dosya 15 sheet içeriyor:

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

İlk dashboard uploadunda:

- 2026 / Şubat / 7. hafta algılandı.
- source/stored: **21,930 / 21,930**.
- import publish edilmedi; atomik rollback oldu.
- önceki güvenli dönem verisi korunmuştur.

---

# 3. İLK KÖK NEDEN — OFFICIAL NATIONAL/REGION AGGREGATE

İlk gerçek traceback:

`ValueError: NATIONAL/bölge reconciliation başarısız: 12 TL/KUTU uyuşmazlığı`

Kaynak Excel verisi incelendiğinde NATIONAL ve 11 region subtotal toplamları gerçekten uyumluydu. Yani problem kaynak veride değildi; importer region subtotal kimliğini yanlış çıkarıyordu.

7. hafta `BAKİYE` pivotunda aynı hierarchy alanları farklı metric bloklarında tekrar ediyor. Örneğin region subtotal satırlarında:

- aynı region label birden fazla dimension hücresinde tekrarlanabiliyor,
- bazı preceding dimension hücrelerinde sayısal `0` placeholder bulunabiliyor.

Eski seçilmiş representative/location kolonu yaklaşımı bu `0` placeholderı gerçek location gibi yorumlayıp bazı region subtotal satırlarını aggregate olarak kaçırabiliyordu.

Çözüm PR #218 ile **row-wide semantic aggregate identity** olacak şekilde genelleştirildi:

- dosya adına, hafta numarasına veya sabit kolon numarasına özel hard-code yok;
- tüm satırdaki anlamlı metinsel dimension hücreleri okunur;
- numeric placeholderlar, özellikle `0`, dimension identity olarak kabul edilmez;
- NATIONAL semantik olarak tanınır;
- tek unique region code ve tekrar eden aynı region identity varsa region subtotal kabul edilir;
- region + farklı representative/kadro/vacancy text varsa person row kabul edilir ve region aggregate yapılmaz;
- iki farklı region code veya belirsiz kimlik varsa fail-closed davranılır;
- strict NATIONAL ↔ region reconciliation gevşetilmemiştir.

Gerçek 7. hafta workbook üzerinde bu semantic kural:

- `BAKİYE`: tam **1 NATIONAL + 11 region subtotal**,
- `TTS HAFTALIK ÇIKIŞLARI`: tam **1 NATIONAL + 11 region subtotal**,
- temsilci satırlarının hiçbiri aggregate olarak yanlış sınıflanmıyor.

Bu problem çözülmüştür.

---

# 4. KALICI PRODUCTION IMS SERVER BENCHMARK

PR #220 ile kalıcı benchmark altyapısı eklendi.

Workflow:

`.github/workflows/ims-server-benchmark.yml`

Script:

`benchmark_ims_import.py`

Davranış:

- başarılı production deploy sonrasında otomatik tetiklenir;
- ayrıca `workflow_dispatch` ile elle çalıştırılabilir;
- canlı `instance/ipm.db` üzerinde import yapmaz;
- `sqlite_online_backup.py` ile `/tmp/ims-benchmark-<timestamp>.db` oluşturur;
- importu bu izole DB kopyasında production host CPU/RAM/disk koşullarında çalıştırır;
- test sonunda geçici `.db`, `.db-wal`, `.db-shm` dosyalarını siler;
- benchmark sırasında service restart edilmez;
- aynı anda tek benchmark çalışması için concurrency group kullanılır;
- toplam süre, importer stage süreleri, peak RSS, counts, reconciliation ve blocker sonuçlarını ölçer;
- canlı DB üzerinde benchmark sonrası WAL + integrity check yapar;
- sonucu GitHub issue olarak kalıcı evidence şeklinde yayınlar.

Disk davranışı:

- ilk gerçek benchmarkta temporary DB boyutu: **251,056,128 bytes (~239 MiB)**.
- geçici DB test sonunda temizlenir.
- kalıcı disk overhead yalnız script/workflow dosyalarıdır.

RAM / CPU davranışı:

- ilk gerçek benchmark `/usr/bin/time` max RSS: **482,204 KB (~471 MiB)**.
- importer telemetry peak RSS: **493,776,896 bytes (~471 MiB)**.
- CPU: **97%**.

---

# 5. İLK GERÇEK SERVER BENCHMARK SONUCU

Workflow:

**IMS Server Import Benchmark — run `33011201630`**

Job:

`Benchmark latest failed IMS on production host`

Result: **FAILED**

Kalıcı evidence:

**Issue #222 — IMS server import benchmark FAILED**

Benchmark doğru dosyayı seçti:

- source upload id: **7**
- file: `Tayfun_7.Hafta_Subat_Brick_Analizi_.xlsx`
- year: 2026
- month: 2
- week: 7
- previous status: FAILED

Ölçülen süreler:

- `/usr/bin/time elapsed`: **597.19 s** (~9 dk 57 sn)
- importer processing: **584.75 s**
- instrumented stage total: **525.4852 s**
- unattributed: **59.2628 s**

Stage dağılımı:

- `competition_import`: **246.3185 s**
- `stage_raw_rows`: **209.1879 s**
- `validate_and_load_workbook`: **36.0906 s**
- `facts_summary_and_official_aggregates`: **14.4008 s**
- `discover_and_prepare_sheets`: **11.1679 s**
- `assignments_and_targets`: **8.3193 s**
- `source_reconciliation`: **0.0002 s**, FAIL

Bu ölçüm dashboarddaki 3–5 dakikalık kullanıcı gözleminin gerçek ve ciddi bir performans problemi olduğunu doğruluyor. İzole server benchmarkta tam import yaklaşık 10 dakika sürdü.

---

# 6. ŞU ANKİ GERÇEK BLOCKER — 481 UNRESOLVED REPRESENTATIVE ROW

Aggregate problemi çözülmüş durumda. Yeni benchmarkta gerçek fail nedeni:

`IMS veri bütünlüğü doğrulaması başarısız: unresolved_representative_rows = 481`

Diğer blocking alanları:

- blank_metric_records: 0
- invalid_metric_records: 0
- row_errors: 0
- unclassified_records: 0
- unmatched_product_records: 0

Benchmark reportta final counts rollback nedeniyle:

- fact: 0
- competition: 0
- raw: 0
- summary: 791
- target: 791
- source_record_count: 21930
- stored_source_record_count: 21930
- reconciliation_status: FAILED

Bu `fact=0 / competition=0 / raw=0`, veri yok anlamına gelmez; import exception sonrası atomik rollback sonucudur.

Logda unmatched representative örnekleri:

- `TULIN BIRCAN KURT`
- `AKIN BORA GOCER`
- `DILARA YIGIT`
- `KUTAY YAZMAN`
- `DAMLA ARIZ`
- `SEVVAL SEN`
- `KUDRET OZDEN`
- `SELMAN TORUN`
- `GOKHAN SEN`
- `AYDEMIR KARAKOC`
- `SERTAC ALBAYRAK`
- `YUSUF PALANCI`
- `SERKAN SARMAN`
- `SONER YESILKAYA`
- `SEDA VAROL`
- `NILDA OZDEMIR`
- `MELISA CICEK`
- target side örnekleri: `IZMIR BOS BRICK`, `CEM TOPCU`, `CEM HARBEK`, `OGUZHAN UGURLU`

Bu liste hard-code edilmemeli; yalnız forensic örnek olarak kullanılmalıdır.

---

# 7. CODEX İÇİN BİRİNCİ ÖNCELİKLİ GÖREV

**481 unresolved representative row problemini sistematik ve semantik olarak çöz.**

Amaç IMS dosyasını sisteme uydurmak değil, sistemi değişken IMS dosyalarını otomatik algılayacak şekilde güçlendirmektir.

Kesin kurallar:

1. Dosya adına, hafta numarasına, sheet satır numarasına veya tek tek temsilci adına özel hard-code EKLEME.
2. Existing Representative / assignment / vacancy / region history yapısını önce analiz et.
3. `BOS` ve `BOŞ` ayrı stable identity olarak kalmalı.
4. `BOSTANCI` vacancy değildir.
5. Historic vacancy PK reuse korunmalı.
6. Accent/case/spacing normalization yalnız güvenli identity resolution için kullanılabilir.
7. İki veya daha fazla gerçek candidate varsa tahmin etme; fail-closed kal.
8. Eski/person history ile yeni IMS adlarının period-effective eşleşmesini kullan.
9. `BRICK REA.` gibi matrix/pivot sheetlerde row grain'i anlamadan satırı representative olarak zorla eşleme.
10. Kaynak row'daki region/brick/representative birlikte değerlendirilerek semantic candidate narrowing yapılmalı.
11. Canonical representative çözümünde region consistency kontrolü korunmalı.
12. Yeni temsilci gerçekten yeni ise otomatik onboarding mekanizması mevcut business kurallarına göre yapılmalı; fakat eski temsilciyi yeni kişi sanıp duplicate oluşturma.
13. Vacancy identity ile normal representative identity ayrıştırılmalı.
14. 481 unresolved satırın tamamını kategoriye ayır: gerçek yeni kişi, eski isim varyasyonu, vacancy/brick pseudo-row, subtotal/aggregate row, gerçek ambiguity, parse-grain hatası.
15. Çözümden sonra unresolved count **0** olmadan production publish kabul edilmemeli.

Özellikle `BRICK REA.` sheetinde çok sayıda unmatched representative warning oluştu. Bu, yalnız isim alias eksikliği değil, sheet row-grain / representative extraction semantiği problemi olabileceği için önce row yapısını incele.

---

# 8. CODEX İÇİN İKİNCİ ÖNCELİKLİ GÖREV — IMPORT PERFORMANSI

Representative blocker çözüldükten sonra import performansını optimize et.

İlk gerçek benchmarkta iki ana darboğaz:

- `competition_import`: **246.3 s**
- `stage_raw_rows`: **209.2 s**

Toplam yaklaşık **455.5 s** yalnız bu iki aşamada gidiyor.

Ek unattributed süre: **59.3 s**.

Hedef:

- doğruluk ve fail-closed gate'leri kaldırmadan süreyi ciddi biçimde azalt;
- önce profiler/telemetry ile gereksiz workbook reread, Python-level nested iteration, row-by-row ORM/SQLite writes, repeated normalization/lookup ve duplicate scans olup olmadığını kanıtla;
- optimize etmeden önce baseline değerleri kaydet;
- her optimizasyon sonrası aynı gerçek 7. hafta benchmarkını production host izole DB kopyasında tekrar çalıştır;
- peak RAM mevcut ~471 MiB değerinden kontrolsüz biçimde büyümemeli;
- 1 GB RAM + swap bulunan production VM dikkate alınmalı;
- aynı anda iki benchmark zaten concurrency ile engellenmiştir.

Kesinlikle yapılmaması gerekenler:

- validation/reconciliation kapılarını kaldırmak;
- unresolved representative satırlarını sessizce skip etmek;
- source/stored eşitliği kontrolünü gevşetmek;
- NATIONAL/region official aggregate otoritesini kişi toplamıyla değiştirmek;
- gerçek `0` değerlerini blank kabul etmek;
- bütün workbooku sınırsız RAM'de duplicate kopyalarla tutmak;
- SQLite WAL/single-writer yapısını rastgele değiştirmek.

---

# 9. TEST / CI / DEPLOY SIRASI

Her kod değişikliğinde zorunlu sıra:

1. Güncel `main`den ayrı branch aç.
2. Hedefli regression testleri ekle.
3. Yerel/CI full suite PASS.
4. 50-upload SQLite scale probe PASS.
5. PR aç.
6. Full CI green olmadan merge etme.
7. Merge sonrası production deploy workflow'u çalışsın.
8. Production acceptance, resource, integrity/WAL, representative performance ve health gate'leri PASS olmadan restart/tamamlandı iddiası verme.
9. Yeni kalıcı `IMS Server Import Benchmark` çalışmasını bekle.
10. Gerçek 7. hafta workbookunda:
   - source/stored 21930/21930,
   - unresolved representative 0,
   - invalid/product/conflict 0,
   - FACT > 0,
   - competition > 0,
   - raw > 0,
   - summary 791,
   - target 791,
   - NATIONAL/11 region reconciliation PASS
   doğrulanmalı.
11. Yalnız bunlardan sonra kullanıcıya dashboard üzerinden aynı 7. hafta dosyasını tekrar yüklemesi söylenmeli.

---

# 10. GUNİCORN / DASHBOARD AVAILABILITY NOTU

Upload sonrası Gunicorn `post_request` hook'u POST `/ims/upload` isteğini işleyen worker'ı memory release amacıyla recycle ediyor.

İlk başarısız 7. hafta uploadunda:

- upload request bittikten sonra worker recycle edildi;
- yaklaşık birkaç saniyelik windowda kullanıcı `ERR_EMPTY_RESPONSE` gördü;
- yeni worker boot olunca dashboard kendiliğinden düzeldi.

Bu availability konusu import data blockerından ayrıdır.

Şimdilik:

- 1 GB RAM host üzerinde körlemesine worker sayısını artırma;
- önce import peak RAM ve worker overlap riskini ölç;
- gerekirse upload endpoint recycle mekanizmasını zero-gap hale getirecek çözümü ayrı PR olarak ele al.

---

# 11. DEĞİŞTİRİLMEYECEK BUSINESS KURALLARI

- P2 > P1 > IMS.
- Product-level fallback korunur.
- Gerçek 0 blank değildir.
- NATIONAL/region official aggregate kişi toplamıyla ikame edilmez.
- Official Brick Spread side-channel masterdır; FACT değildir.
- BOS != BOŞ.
- BOSTANCI normal isimdir; vacancy değildir.
- Historic vacancy PK reuse korunur.
- Ambiguous identity guess edilmez.
- Prime / target / realization / %100+ business rules keyfi değiştirilmez.
- SQLite WAL + `busy_timeout=30000` + single-writer korunur.
- User vault ayrı korunur.
- Failed import yarım publish edilmez.
- Production acceptance fail olursa canlı snapshot korunur.
- Full CI green olmadan merge yok.
- Production acceptance PASS olmadan restart yok.

---

# 12. CODEX'E VERİLECEK DEVAM KOMUTU

Codex bu dosyayı ve `PROJECT_WORK_PROGRESS.md` dosyasını okuyup aşağıdaki görevden başlamalı:

> Güncel main'den başla. 7. hafta gerçek server benchmarkında `unresolved_representative_rows=481` blockerını kök neden seviyesinde çöz. Tek tek isim veya dosya/week hard-code etme. Önce unresolved satırları kategori/grain olarak analiz et, özellikle `BRICK REA.` representative extraction ve vacancy/region/person identity resolution akışlarını doğrula. Deterministik semantic resolution geliştir, regression testlerini ekle, full CI + 50-upload scale PASS al. Ardından production deploy/acceptance sonrası kalıcı `IMS Server Import Benchmark` ile gerçek `Tayfun_7.Hafta_Subat_Brick_Analizi_.xlsx` dosyasını izole DB'de yeniden test et. Unresolved=0 ve bütün import/reconciliation gate'leri PASS olmadan dashboard yeniden upload önermeyin. Sonra `competition_import` ve `stage_raw_rows` toplam ~455 saniyelik darboğazını profiler kanıtıyla optimize et; doğruluk gate'lerini gevşetme.

---

# 13. REFERANSLAR

- PR #218: semantic row-wide official aggregate identity fix.
- PR #220: isolated production IMS import benchmark.
- Main SHA: `7786fab25716f241f294cc739731aa2ce74672ad`.
- Production deploy workflow #493 / run `33009859122`: SUCCESS.
- IMS Server Import Benchmark run `33011201630`: FAILED.
- Issue #222: `IMS server import benchmark FAILED`.
- Real benchmark DB copy size: 251,056,128 bytes.
- Real benchmark max RSS: 482,204 KB.
- Real benchmark CPU: 97%.
- Real benchmark elapsed: 597.19 s.
- Import processing: 584.75 s.
- Source/stored: 21,930 / 21,930.
- Current real blocker: `unresolved_representative_rows=481`.
