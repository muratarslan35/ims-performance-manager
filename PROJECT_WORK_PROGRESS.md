# IMS Performance Manager — Kanonik Çalışma / Devir Kaydı

> Son güncelleme: **24 Ağustos 2026 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Bu dosya PC Codex, mobil ChatGPT ve sonraki çalışma oturumları için **tek güncel checkpoint** olarak kullanılmalıdır.

---

# 1. AKTİF DURUM — BURADAN DEVAM ET

## Production

- Canlı uygulama kod SHA: **`73c64343f5555db5087b7a4120e64018c2ffeb0a`**
- Bu SHA PR **#147 — Memoize representative market period reads** merge commitidir.
- Production workflow: **`32759379739`**
- Kalıcı deployment evidence: **Issue #148 — IMS production deployment SUCCESS**
- Production host: `130.162.48.162:8000`
- Service: `ims-performance-manager.service`
- Oracle Cloud Frankfurt; yaklaşık 2 CPU / 1 GB RAM / 2 GB swap.
- SQLite: WAL, `busy_timeout=30000`, integrity OK.
- Production `/login` health check: **PASS**.
- Acceptance sonrası gerçek systemd service restartı tamamlandı.

> Bu dosyanın daha sonraki yalnız-dokümantasyon commit SHA'sı production kod SHA'sından farklı olabilir. `PROJECT_WORK_PROGRESS.md`-only main push'ları deploy workflow'da `paths-ignore` ile hariç tutulmuştur; böylece checkpoint güncellemesi gereksiz production restart oluşturmaz.

## Şu an açık kritik blocker

**Yok.**

Şubat IMS yüklemelerine devam edilebilir. Tüm IMS tarihçesi bitene kadar final Türkiye Pazar Analizi oluşturulmayacak.

---

# 2. 24 AĞUSTOS 2026 — ŞUBAT 6. HAFTA PERFORMANS OLAYI VE ÇÖZÜMÜ

Şubat **6. hafta IMS** yüklendikten sonra:

- login sonrası `/dashboard/` server-side yanıtı yaklaşık **11 saniyeye** çıktı;
- sayfalar genel olarak ağırlaştı;
- loglarda 500/traceback yerine uzun request süreleri görüldü;
- IMS importu aynı Gunicorn web worker içinde pandas/openpyxl ile çalışıyordu;
- worker `max_requests` süresince yaşamaya devam ettiği için küçük ~1 GB hostta import sonrası retained heap + swap baskısı oluşabildi.

Kullanıcı production'da manuel:

```bash
sudo systemctl restart ims-performance-manager.service
ims-kontrol
```

çalıştırdı. Sonuç:

- otomatik başlatma: `enabled`
- çalışma durumu: `active`
- dashboard yeniden **1 saniyeden hızlı** açıldı.

Bu canlı A/B gözlemi, ana yavaşlığın Şubat verisinin kalıcı DB sorgu maliyetinden değil import sonrası worker memory/swap pressure'dan kaynaklandığını güçlü biçimde doğruladı.

## Kalıcı çözüm — PR #145

PR #145 merge SHA:

`783a000389c08408e36376f93b9355371c31b569`

Gunicorn `post_request` koruması:

- yalnız `POST /ims/upload` isteğini işleyen worker response tamamlandıktan sonra graceful recycle edilir;
- diğer worker hizmet vermeye devam eder;
- pandas/openpyxl importundan kalan process heap yeni worker ile bırakılır;
- normal dashboard/login requestleri worker recycle etmez;
- DB transaction, import lock, WAL ve IMS business semantiği değişmez.

PR #145 final CI:

- 307 collected
- 305 passed
- 2 skipped
- 0 failed
- 50-upload / 5,000,000 competition-row scale probe PASS.

PR #145'in ilk production denemesi Issue #146'da representative query budget nedeniyle service restarttan önce güvenli biçimde durdu: `31 SELECT > 30`. Bu failure artık **Issue #148 SUCCESS tarafından superseded** edilmiştir.

## Query tekrarlarının kaldırılması — PR #147

PR #147:

- `(year, month) -> latest IMS upload id` aynı `RepresentativeMarketService` build'i içinde memoize edilir;
- `(year, month) -> brick/fallback scope` aynı build içinde memoize edilir;
- memo yalnız service instance/build ömründedir; process/global stale cache değildir;
- `build()` başlangıcında sıfırlanır;
- aggregate competition / raw brick / exact brick competition aynı aktif upload ve brick scope'u tekrar SELECT etmez;
- performans eşiği gevşetilmemiştir; gerçek redundant sorgular kaldırılmıştır.

Regression testi:

`tests/test_representative_market_query_memoization.py`

- aynı current-period upload sorgusu bir kez;
- aynı representative brick-scope sorgusu bir kez çalışmak zorundadır.

PR #147 final CI run: **#406 / `32759129475`**

- **308 collected**
- **306 passed**
- **2 skipped**
- **0 failed**
- 50-upload scale probe PASS
- synthetic rows: 5,000,000 competition / 1,404,550 raw / 158,200 fact
- competition six-upload query: ~0.0109 s
- latest fact: ~0.0014 s
- raw brick: ~0.0001 s
- integrity OK.

---

# 3. PRODUCTION SUCCESS — ISSUE #148

Commit:

`73c64343f5555db5087b7a4120e64018c2ffeb0a`

Workflow:

`32759379739`

Result: **SUCCESS**

## Representative performance — 2026/02

Issue #146 öncesi → Issue #148 sonrası:

- max total SELECT: **31 → 26** (`threshold=30`)
- warm SELECT: **25 → 20**
- max competition SELECT: **4 / threshold 4**
- unscoped competition SELECT: **0**
- cold max/p95: **0.6698 s**
- warm max/p95: **0.1296 s**
- result: **PASS**

Bu nedenle query eşiği yükseltilmeden gerçek tekrar sorguları kaldırılmıştır.

## SQLite / capacity

- journal mode: WAL
- busy_timeout: 30000
- integrity: OK
- active DB: **250,650,624 bytes**
- disk free at capacity gate: **36,187,828,224 bytes**
- +49 IMS estimated active DB growth: **3,307,748,307 bytes**
- storage projection: **PASS**
- blocking: `[]`
- bütün gerekli kompozit indeksler mevcut
- competition/fact/raw/summary/target query planları bounded/indexed: PASS.

Current production row counts:

- `ims_competition_data`: **386,300**
- `ims_facts`: **10,472**
- `ims_raw_data`: **97,353**
- `ims_summary`: **1,582**
- `ims_uploads`: **4**
- `targets`: **1,582**

## Şubat 6. hafta IMS acceptance

Baseline workbook:

`Tayfun-1_6.Hafta_Subat_Brick_Analizi_.xlsx`

- year/month/week: `2026 / 2 / 6`
- source records: **28,098**
- stored source records: **28,098**
- competition: **99,756**
- fact: **3,164**
- summary: **791**
- target: **791**
- official aggregates: **168**
- sheets: **16/16 verified**
- representatives: **113**
- regions: **11**
- products: **7**
- vacancies: **11**
- zero metrics: **3,197** (gerçek veri olarak korunuyor)
- unresolved representative/product: **0**
- invalid metric / row error / duplicate conflict / conflicting match: **0**
- national/region target + actual consistency: **PASS**
- manager report: **PASS**
- IMS acceptance: **PASS**
- IMS acceptance extras: **PASS**

Şubat 6. hafta toplamları:

- summary TL: **18,480,007.44**
- summary UNIT: **192,446**
- target TL: **134,284,969.30908635**
- target UNIT: **1,196,980**

## Restart / health / worker recycle

Production workflow acceptance kapılarının tamamı geçtikten sonra managed systemd service yeniden kuruldu/restart edildi ve `/login` health **PASS** oldu. Böylece PR #145'te eklenen **post-IMS upload worker recycle artık canlı production runtime'dadır**.

Bundan sonraki büyük IMS uploadlarında upload'u yapan worker response sonrasında yenilenir; kullanıcının her IMS'ten sonra manuel `systemctl restart` yapması gerekmemelidir.

## Backup retention

Issue #148 retention sonucu PASS:

- yeni doğrulanmış rollback stamp: `20260824-175726`
- retained managed: current IPM predeploy + competition-backfill + users predeploy
- retained integrity: IPM `ok`, users `ok`

Not: backup klasöründe PC Codex döneminden kalan birkaç `.bak` adlı unmanaged güvenlik kopyası retention aracı tarafından korunmuştur. Bunlar current deployment blocker değildir; otomatik managed rollback setinden ayrıdır. Silme kapsamı ayrıca değiştirilmeden tutulmuştur.

---

# 4. KULLANICININ AKTİF IMS ÇALIŞMA PLANI

- Ocak IMS yüklemeleri tamamlandı.
- Şubat IMS yüklemelerine geçildi.
- 6. hafta Şubat IMS production DB'ye doğrulanmış şekilde yüklendi.
- Sonraki Şubat IMS dosyaları sırayla yüklenecek.
- Tüm IMS dosyaları tamamlanana kadar Türkiye Pazar Analizi final olarak kurulmayacak.
- Tüm IMS tarihçesi yüklendikten sonra Türkiye Pazar Analizi toplu üretilecek.
- Hedef kırılımlar: Türkiye → bölge → il → brick; ürün grubu → rakip ürün; aylık / 3 aylık / 6 aylık / yıllık.
- Gerçek `0` data olarak korunacak; eksik veri sıfır diye uydurulmayacak.

---

# 5. PC CODEX İLE 23–24 AĞUSTOS'TA GELEN ÖNEMLİ İLERLEMELER

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

# 6. DEĞİŞTİRİLMEYECEK BUSINESS KURALLARI

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

# 7. BOS / BOŞ / VACANCY KURALLARI

- `BOS != BOŞ`.
- `DİYARBAKIR BOS != DİYARBAKIR BOŞ`; ayrı stable Representative ID.
- `BOS KADRO` / `BOŞ KADRO` slot identity korunur.
- `BOSTANCI` vacancy değildir.
- `BRICK` tek başına vacancy identity değildir.
- Deterministik tek eşleşme yoksa tahmin yapılmaz.
- Vacancy resolution başarısızsa accent-insensitive fuzzy fallback yapılmaz.
- Historic vacancy PK korunur; duplicate Representative oluşturulmaz.

---

# 8. IMS IMPORTER SÖZLEŞMESİ

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

# 9. SQLITE / UZUN DÖNEM DB KARARI

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

# 10. PERFORMANS MİLESTONE'LARI

## Temsilci ekranı

Eski 25–30 saniyelik temsilci detail problemi daha önce giderildi. Şubat 6. hafta son production sonucu (#148):

- cold max/p95: **0.6698 s**
- warm max/p95: **0.1296 s**
- max competition SELECT: **4**
- max total SELECT: **26**
- unscoped competition SELECT: **0**
- result: **PASS**.

## SQLite scale

PR #141 ve sonraki gate'ler:

- WAL / busy_timeout korunuyor;
- connection cache / mmap / temp_store optimizasyonları;
- post-import `PRAGMA optimize` + `wal_checkpoint(PASSIVE)`;
- otomatik full VACUUM yok;
- +49 IMS capacity gate PASS;
- synthetic 50-upload / 5M competition probe bounded indexed queries PASS.

---

# 11. ORACLE ALTYAPI KARARI

Yeni Always Free Ampere A1 denendi:

- Frankfurt AD1/AD2/AD3 `VM.Standard.A1.Flex` → Out of capacity;
- 2 OCPU / 12 GB ve 1 OCPU / 6 GB denendi;
- mevcut IMS production VM silinmedi;
- ücretli shape'e geçilmedi.

Şimdilik mevcut Free production ile devam ediliyor. İleride A1 veya ücretli güçlü sunucu bulunursa migration paralel staging + acceptance ile yapılacak; eski production yeni makine tam PASS olmadan kapatılmayacak.

---

# 12. SONRAKİ ADIM

1. Şubat IMS yüklemelerine sırayla devam et.
2. Her IMS uploadundan sonra service genel performansını gözle; worker recycle nedeniyle manuel restart normalde gerekmemeli.
3. Yeni IMS'de manager report / import acceptance warning çıkarsa dosyayı tahminle kabul etme; blocker'ı kaynaktan çöz.
4. Önemli her kod/veri/deploy değişikliğinde bu `PROJECT_WORK_PROGRESS.md` dosyasını güncelle.
5. Tüm IMS tarihçesi tamamlanınca bütün dönemleri kullanan Türkiye Pazar Analizi'ni topluca tasarla ve kur.
