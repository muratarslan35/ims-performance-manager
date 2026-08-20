# IMS Performance Manager — Çalışma Checkpointi / Kanonik Devir Kaydı

> Son güncelleme: **20 Ağustos 2026, 07:37 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Bu dosya çalışma ortamında devam ederken **tek referans checkpoint** olarak kullanılmalıdır.

---

# 1. ŞU ANKİ DURUM — ÇALIŞMA ORTAMINDA BURADAN DEVAM ET

## Ana sonuç

IMS import/parser/matching/reconciliation altyapısının profesyonel hardening çalışması tamamlanmaya çok yaklaşmıştır. PR #65, #66 ve #67 `main` branch'e merge edilmiştir. Tam test paketi yeşildir. Ancak production acceptance gerçek 4. hafta workbookunu yeniden import ederken **Official Brick Spread içindeki BOS kadrolarının merkezi vacancy resolver üzerinden çözülmediğini** yakalamıştır.

**Canlı servis bu hata nedeniyle yeniden başlatılmadı.** Deploy workflow acceptance PASS olmadan process restart aşamasına geçmeyecek şekilde korunmaktadır.

### En son `main` commit

- `45327c332e0dc82aac407f545575e4c1353cac21`
- Mesaj: `Merge PR #67: Fix isolated IMS acceptance FACT fingerprint scope`

### En son gerçek production acceptance sonucu

- GitHub Issue: **#69 — IMS production deployment FAILED**
- Commit: `45327c332e0dc82aac407f545575e4c1353cac21`
- Workflow: `32306554405`
- SQLite runtime kontrolü: **PASS**
  - `journal_mode=wal`
  - `busy_timeout=30000`
  - `integrity=ok`
- Acceptance: **FAIL**
- Kök hata:
  - `Satış Brick Yayılımı master satırlarında eşleşmeyen temsilci var (11)`
  - Issue çıktısında görünür satırlar:
    - satır 18: `ISTANBUL BOS`
    - satır 35: `KADIKOY BOS`
    - satır 46: `BURSA BOS`
    - satır 50: `IZM BOS BRICK`
    - satır 66: `ANKARA BOS`
    - satır 79: `SAMSUN BOS`
    - satır 88: `TRABZON BOS`
    - satır 100: `ADANA BOS`
    - satır 108: `KONYA BOS`
    - satır 116: `ANTALYA BOS`
  - Hata mesajı toplam 11 eşleşmeyen satır olduğunu söylüyor; GitHub issue özetinde 10 isim görünür durumda, 11. satır özet içinde kesilmiş olabilir. **Tahmin edilmemeli; workflow/job logundan okunmalı.**

## Çalışma ortamındaki bir sonraki kesin iş

**OfficialBrickSpreadService / official brick spread import yolunu merkezi `RepresentativeResolver` ile aynı vacancy çözümleyiciye bağla.**

Kurallar:

1. `BOS` ile `BOŞ` kesinlikle aynı kadro değildir.
2. Vacancy eşleşmesi accent-sensitive stable identity kullanmalıdır.
3. `BOSTANCI` gibi normal isimler vacancy sayılmamalıdır.
4. Vacancy resolver başarısızsa normal accent-insensitive alias/fuzzy zincirine geri düşülmemelidir.
5. Official Brick Spread parserı kendi ayrı/legacy representative eşleştirmesini kullanmamalıdır.
6. Belirsiz eşleşme tahmin edilmemeli, import blocking conflict olarak durmalıdır.
7. Bu düzeltme FACT/SUMMARY/prim/P2>P1>IMS iş mantığını değiştirmemelidir.

Düzeltmeden sonra sırasıyla:

1. BOS/BOŞ/BOSTANCI + official brick spread regression testleri.
2. Tam `pytest tests/ -v`.
3. PR/merge.
4. Production workflow.
5. İzole gerçek workbook re-import/fingerprint acceptance.
6. Manager PASS raporu + manifest + NATIONAL/region + BOS/BOŞ stable-ID acceptance.
7. Ancak bunların tamamı PASS ise servis restart ve `/login` health smoke.

---

# 2. DEĞİŞTİRİLMEMESİ GEREKEN CANLI İŞ KURALLARI

Bu hardening çalışmasının temel şartı mevcut doğru business davranışını bozmamaktır.

- Production satış kaynağı önceliği: **P2 > P1 > IMS**.
- P1 geldiğinde IMS beklenmez; P2 geldiğinde P1'in yerini alır.
- P2 tek başına da final kaynak olabilir.
- Production realizasyonu `%100` üzerinde **kırpılmaz**.
- Nationwide snapshot farklı satış kaynaklarını birbirine karıştırmaz.
- Prime engine kuralları ve mevcut payout davranışı korunur.
- Dashboard/region/representative ekranlarında mevcut doğru hesaplar yeniden tasarlanmaz.
- Hedef business source/schema keyfi değiştirilmez.
- Official NATIONAL/region toplamı kişi toplamıyla ikame edilmez.
- Official Brick Spread FACT domainine karıştırılmaz; ayrı master/side-channel veri olarak kalır.
- Kullanıcı kasası (`instance/persistent/users.db`) bağımsız korunur.
- Ana SQLite DB WAL modunda kalır; import single-writer koordinasyonu korunur.
- Import validation failure durumunda mevcut canlı IMS yayında kalır; yarım import publish edilmez.

---

# 3. 9–18 AĞUSTOS DÖNEMİNDE TAMAMLANAN TEMEL ÇALIŞMALAR — ÖZET

Bu bölüm önceki uzun checkpoint dosyasındaki önemli tamamlanmış işleri kaybetmemek için konsolide edilmiştir.

## Import / competition / hedef

- `app/services/competition_import_service.py`
  - Gerçek Excel'deki `AYLIK REKABET TL`, `AYLIK REKABET KUTU`, `TTS Rekabet`, `TTS Rekabet PP` yapıları desteklenmiştir.
  - Tek-geçişli veri okuma optimizasyonu yapılmıştır.
  - Gerçek 24. hafta importunda 91.070 rekabet kaydı işlenmiştir.
- `app/services/target_import_service.py`
  - `TTS ÇIKIŞLARI` içindeki kompakt hedef blokları desteklenmiştir.
- `app/services/ims_import_service.py`
  - RAW → FACT grain aggregation düzeltildi; aynı representative/product için brick satırlarının birbirini ezmesi engellendi.
  - Birleştirilmiş header'lardan TL/KUTU semantiği taşınmıştır.
- Upload route yıkıcı `clear_before_import=True` davranışından güvenli idempotent akışa geçirilmiştir.
- Competition migration/API zinciri kurulmuştur.

## Dashboard ve veri akışı

- Global dashboard aggregate payload'a geçirilmiştir.
- PrimeEngine için sahte `representative_id=0` kullanımı kaldırılmıştır.
- PP trendi gerçek competition kaynağına bağlanmıştır.
- AI payload alanları null-safe sözleşmeye alınmıştır.
- Temsilci/brick arama, region performance ve representative detail ekranları gerçek dönem verilerine bağlanmıştır.
- Mobile navbar aktif dönem + son IMS + search içerecek şekilde tamamlanmıştır.

## Hedef / kutu hedef

- Yanlış kutu hedef türetme denemesi kaldırıldıktan sonra iş kuralı netleştirilmiş ve ortak servis üzerinden `unit_target = tl_target / approved product.unit_price` yaklaşımı uygulanmıştır.
- `target_box_calculation_service.py` eklenmiştir.
- Target ekranı representative accordion yapısına geçirilmiştir.

## Brick assignment

- `representative_brick_assignments` dönemsel altyapısı eklenmiştir.
- Manual assignment AUTO import ile ezilmez.
- Aynı brickte birden fazla geçerli üye desteklenmiştir; satış FACT'ı çift sayılmaz.
- Eski 24. hafta için 789 brick / 798 representative-brick membership backfill edilmiştir.

## Prime / Q

- Aylık entitlement: dört ana ürünün tümü >=%75, en az üçü >=%90 ve toplam TL >=%100 şartları uygulanmıştır.
- `%100+` business davranışı korunmuştur.
- Q dönem analizi ayrı ekran olarak eklenmiştir.
- Eski checkpoint commitleri arasında `48c1add`, `cb3ae71`, `f08433b`, `e310c5f`, `e8f2ae8` bulunmaktadır.

## UI / dark mode

- Login dahil uygulama genelinde koyu mod okunabilirlik düzeltmeleri yapılmıştır.
- Global realizasyon gösterimi normalize edilmiştir.
- İlgili merge commitlerinden biri: `ce82fd2ba816df36d2f72cf61d07cfd2746902d9`.

## SQLite / kullanıcı kasası / deploy dayanıklılığı

- WAL runtime, busy timeout ve single writer import lock uygulanmıştır.
- Auth okumaları transient SQLite lock sırasında korunmuştur.
- Kullanıcı kasası ana DB'den bağımsız fallback olarak korunmuştur.
- WAL-safe online backup utility eklenmiştir.
- Production deploy öncesi ana DB + user vault yedekleri alınır.
- Bu hardening merge commitlerinden biri: `c184a956278645e66497a0558611eb9118bcebbd`.

## Official Brick Spread ilk entegrasyonu

- Official Brick Spread master değerleri FACT'e karıştırılmadan saklanmıştır.
- PR #64 merge commit: `d17c6c70d22e047e2893bed7b469aa206c4f06c7`.
- Daha sonra 19–20 Ağustos reconciliation hardening'i bu yapıyı content-driven/atomic hale getirmiştir.

---

# 4. 19–20 AĞUSTOS — WHOLE-WORKBOOK RECONCILIATION HARDENING

## Amaç

Excel sayfa adı/sırası/kolon koordinatına bağlı kırılgan import yerine, gerçek workbook içeriğinin tamamını kapsayan; semantik, deterministik, atomik ve audit edilebilir bir import/reconciliation mimarisi kurmak.

## PR #65 — IMS workbook reconciliation ve vacancy identity hardening

- PR: `#65`
- Merge commit: `fdb07136062ad1bb2c59eb5fb4e4a614e82985f3`
- Değişiklik kapsamı: 22 dosya, yaklaşık 2.5K ek satır.

### Eklenen / değiştirilen ana katmanlar

- `app/services/workbook_preflight.py`
  - Whole-workbook manifest.
  - Her anlamlı sheet/cell terminal sınıfa gider.
  - Unknown/unclassified sheet blocking olur.
  - Gerçek `0` değerleri blank sayılmaz.

- `app/services/semantic_import_discovery.py`
  - Sheet adı ve sırası business identity olmaktan çıkarıldı.
  - Target/competition/official brick spread content signature ile keşfedilir.
  - Rename/header shift/order change tolere edilir.
  - Belirsizlik varsa tahmin edilmez.

- `app/services/representative_resolver.py`
  - Representative matching tek merkezde toplandı.
  - Normal temsilciler: persistent/exact/alias/normalized/controlled fuzzy.
  - Vacancy: accent-sensitive stable identity.
  - `BOS != BOŞ`.
  - `BOSTANCI` vacancy değildir.
  - Ambiguous match tahmin edilmez.

- `app/services/vacancy_matching.py`
  - Vacancy canonicalization ve slot token ayrımı merkezileştirildi.

- `app/services/derived_master_verification.py`
  - Derived/master karşılaştırması hücre koordinatından semantik key'e taşındı.
  - Anahtar mantığı: region/brick/representative + product/market + metric + phase + period.
  - Tek bir conflicting master value veya eksik beklenen metric blocking olur.
  - Bağımsız master pivot FACT'e duplicate yazılmaz.

- `app/services/workbook_semantic_reconciliation.py`
  - Semantic relationship graph/reconciliation.

- `app/services/official_aggregate_service.py`
  - NATIONAL ↔ region reconciliation.
  - TL ve KUTU ayrı doğrulanır.
  - Kişi toplamı NATIONAL yerine kullanılmaz.

- `app/services/official_brick_spread_atomic.py`
  - Official Brick Spread content-driven keşif.
  - Aynı outer import transaction içinde atomik side-channel persistence.

- `app/services/ims_delta_service.py`
- `app/services/ims_delta_audit.py`
  - Previous IMS delta:
    - satış TL/KUTU
    - hedef
    - representative/product eklenen/çıkan
    - region/cadre
    - official brick spread
    - competition value/grain
  - Değişiklik tek başına hata sayılmaz; audit edilir.

- `app/services/import_result_report.py`
  - Manager-facing PASS/FAIL JSON özeti `ImportAuditLog.notes` içinde saklanır.
  - IMS Merkezi'nde tek seferlik görünür özet sunulur.
  - PASS/FAIL kararı canonical publication blockers ile hizalanmıştır.

- `.github/workflows/deploy.yml`
  - Production deploy acceptance gate.
  - Main DB ve user vault WAL-safe backup.
  - Migration/runtime/target/master snapshot/integrity kontrolleri.
  - Canlı DB üzerinde dry-run yapılmaz.
  - `/tmp/ims-acceptance-*` izole DB kopyası oluşturulur.
  - Aktif COMPLETED IMS workbooku izole DB'de yeniden import edilir.
  - FACT/SUMMARY/TARGET/competition/official brick spread/official aggregates fingerprint ve toplamları karşılaştırılır.
  - Acceptance PASS olmadan process restart yoktur.

- `verify_ims_acceptance.py`
- `verify_ims_acceptance_extras.py`
  - Gerçek workbook re-import/fingerprint.
  - Manager report PASS.
  - Full manifest.
  - Blocking counters = 0.
  - NATIONAL/region reconciliation.
  - Persisted BOS/BOŞ stable ID ayrımı.

### PR #65 test sonucu

GitHub Actions run #236:

- **236 test collected**
- **235 passed**
- **1 skipped**
- **0 failed**

Geçen kritik test alanları:

- P2 > P1 > IMS.
- `%100+` uncapped.
- Nationwide single-source.
- Prime engine / simulation.
- Auth/dashboard routes.
- Dark mode/presentation.
- SQLite WAL/read concurrency/user vault.
- Zero metric gerçek veri.
- Renamed sheet semantic discovery.
- Derived conflict blocking.
- Missing expected derived metric blocking.
- Independent master pivot FACT'e yazılmama.
- `BOS != BOŞ`.
- `BOSTANCI != vacancy`.
- Ambiguous BOS/BOŞ guess edilmemesi.

---

# 5. PR #66 — PRODUCTION DEPLOYMENT EVIDENCE

- PR: `#66`
- Merge commit: `65a428fcbdb3a8e521dfe56c00685782beb09012`
- Amaç: production deploy/acceptance sonucunu yalnız ephemeral Actions logunda bırakmamak.

Yapılan:

- Deploy stdout/stderr yakalanır.
- Sonuç merge SHA ile ilişkilendirilir.
- GitHub issue olarak kalıcı production evidence bırakılır.
- Remote deploy hata verirse workflow yine failure olur; evidence kaydı failure'ı mask etmez.
- Business logic, DB model, dashboard, hedef ve prim davranışı değişmez.

## İlk gözlenebilir production sonucu — Issue #68

- Commit: `65a428fcbdb3a8e521dfe56c00685782beb09012`
- Sonuç: **FAILED**
- Fakat SQLite runtime: **PASS**
  - WAL aktif.
  - busy_timeout 30s.
  - integrity OK.
- Bu koşu sırasında servis restart edilmedi.

Bu aşamada acceptance verifier içinde bir scope problemi tespit edildi.

---

# 6. PR #67 — ACCEPTANCE FACT FINGERPRINT SCOPE FIX

- PR: `#67`
- Merge commit: `45327c332e0dc82aac407f545575e4c1353cac21`

Kök problem:

- FACT upload-versioned olmasına rağmen acceptance snapshot FACT'ı `year/month` ile sorguluyordu.
- İzole re-import yeni upload oluşturduğu için baseline + acceptance FACT satırları aynı period sorgusuna karışarak yanlış fingerprint mismatch üretebilirdi.

Düzeltme:

- FACT snapshot yalnız karşılaştırılan `upload_id` üzerinden alınır.
- Summary/Target mevcut tasarıma uygun olarak period-scoped kalır.
- Business data/runtime logic değişmez; yalnız acceptance verifier doğruluğu düzeltilir.

PR #67 tam CI: **PASS**.

---

# 7. GERÇEK 4. HAFTA WORKBOOKU ÜZERİNDE BAĞIMSIZ KAYNAK KONTROLLERİ

Hardening sırasında gerçek workbook yalnız test fixture değil, acceptance kaynağı olarak tekrar incelendi.

Doğrulananlar:

- Sheet sayısı: **16**.
- Workbookta gerçek sayısal sıfır hücre: **84.007**.
  - Bu nedenle `0 != blank` kuralı kritik ve gerçek veri gereksinimidir.
- Representative/kadro grain: **113 kişi/kadro**.
- Kişi/kadro satış toplamı: **125.767.119,32 TL**.
- Kişi/kadro kutu toplamı: **1.497.003 kutu**.
- Kişi hedef TL toplamı: **137.664.417,843582 TL**.
- Official Brick Spread: **113 x 8 = 904** master değer.
- Bölgesel aggregate: **11 bölge**.
- 11 bölge TARGET TL toplamı NATIONAL ile eşleşti.
- 11 bölge cumulative actual TL toplamı NATIONAL ile eşleşti.
- 11 bölge cumulative actual KUTU toplamı NATIONAL ile eşleşti.
- Ürün bazında resmi hedef kutu aggregate'larında NATIONAL ↔ 11 bölge toplamı uyumludur.

Sonuç:

- NATIONAL/region reconciliation kapısının temel Excel matematiği doğru.
- Kişi toplamının NATIONAL yerine kullanılması gerekmiyor ve kullanılmamalı.
- Güncel production blocker workbook toplamı değil, Official Brick Spread vacancy representative resolution yoludur.

---

# 8. PRODUCTION DEPLOY AKIŞININ ŞU ANKİ GÜVENLİK DAVRANIŞI

Workflow sırası özetle:

1. Full test suite.
2. SSH production bağlantısı.
3. `git fetch/pull main`.
4. Requirements.
5. Main DB WAL-safe predeploy backup.
6. User vault WAL-safe predeploy backup.
7. Master snapshot before migration.
8. Alembic upgrade.
9. Competition backfill öncesi ayrıca DB backup.
10. Competition backfill.
11. Runtime verification.
12. Target audit.
13. Master snapshot after migration.
14. SQLite WAL/busy_timeout/integrity.
15. İzole acceptance DB copy.
16. `verify_ims_acceptance.py`.
17. `verify_ims_acceptance_extras.py`.
18. **Yalnız hepsi PASS ise** eski process kill + yeni process start.
19. `/login` health smoke.
20. Persistent GitHub deployment evidence.

Issue #69 acceptance aşamasında fail olduğu için 18. adıma geçilmedi.

Not: Deploy script `git pull`, migration ve runtime kontrollerini acceptance'tan önce yaptığı için production checkout'un main'e ilerlemiş olması ve additive/idempotent migration/backfill adımlarının çalışmış olması beklenir. Ancak **çalışan Flask process restart edilmediği için yeni hardening kodu canlı process olarak yayınlanmış kabul edilmemelidir.**

---

# 9. ŞU ANDA AÇIK TEKNİK HATA — ROOT CAUSE

## Problem

`Satış Brick Yayılımı` official master parserı, normal representative resolver hardening'inin dışında kalan bir representative matching yolu kullanıyor.

Sonuç:

- Normal kişi adları geçebilirken explicit regional vacancy adları:
  - `ISTANBUL BOS`
  - `KADIKOY BOS`
  - `BURSA BOS`
  - `IZM BOS BRICK`
  - vb.
  central vacancy identity ile çözülmüyor.

Bu durum `RepresentativeResolver` merkezileştirme hedefinin eksik kalan son parser entegrasyonudur.

## Beklenen çözüm tasarımı

Official Brick Spread resolver çağrısı:

1. Source label explicit vacancy ise önce `vacancy_slot_token` / canonical vacancy context üretmeli.
2. Region/city/brick context ile stable vacancy ID çözmeli.
3. `BOS`, `BOŞ`, `BOS KADRO`, `BOŞ KADRO` ayrımı korunmalı.
4. Legacy `UNASSIGNED<region>` placeholder varsa güvenli migration/stable identity kuralı uygulanmalı.
5. Match yoksa normal alias/fuzzy'ye düşmemeli.
6. Non-vacancy adlarda normal `RepresentativeResolver` zinciri kullanılmalı.
7. Aynı resolver TargetImportService, IMS FACT path ve OfficialBrickSpreadService için tek kaynak olmalı.

## Eklenmesi gereken testler

En az:

- `OfficialBrickSpreadService` → `ISTANBUL BOS` persisted vacancy ID'ye eşleşir.
- `IZM BOS BRICK` içindeki `BRICK` context-only kabul edilir.
- `DİYARBAKIR BOS` ve `DİYARBAKIR BOŞ` aynı ID'ye düşmez.
- `BOSTANCI` normal temsilci/yer adı olarak kalır.
- Aynı contextte iki vacancy slot varsa resolver tahmin etmez.
- Production acceptance workbooktaki tüm 11 regional BOS satırı resolved olur.
- Official spread count/fingerprint baseline ile eşleşir.

---

# 10. TAMAMLANMIŞ TEST GÜVENCESİ

Son hardening test paketinde özellikle şu davranışlar korunmuştur:

- IMS before production.
- P1 immediately replaces IMS.
- P2 replaces P1.
- P2 can be final without P1.
- No source = error, not fake zero.
- Nationwide source mixing prohibited.
- Production percent >100 uncapped.
- Decimal precision preserved.
- Region totals include inactive vacant positions.
- Official workbook subtotal preferred for region total while person allocation remains available.
- Box target authoritative values preserved.
- Dashboard competition uses latest real Excel rows.
- IMS time rendered Europe/Istanbul.
- Dynamic representative market analysis.
- Semantic renamed target/competition/brick-spread discovery.
- Unknown meaningful sheet blocks.
- Empty sheet = explicit nondata.
- Zero metric = real data.
- SQLite WAL online backup consistency.
- Concurrent authenticated read survives writer.
- Import coordinator blocks second writer.
- User vault independent identity load.
- Prime entitlement/simulation/export/history suite.

---

# 11. GITHUB KAYITLARI / İLGİLİ PR VE ISSUE'LAR

## Merge edilmiş PR'lar

- PR #64 — Official Brick Spread master source
  - merge: `d17c6c70d22e047e2893bed7b469aa206c4f06c7`
- PR #65 — Whole-workbook reconciliation + vacancy identity hardening
  - merge: `fdb07136062ad1bb2c59eb5fb4e4a614e82985f3`
- PR #66 — Persistent production deployment evidence
  - merge: `65a428fcbdb3a8e521dfe56c00685782beb09012`
- PR #67 — FACT acceptance fingerprint scope fix
  - merge: `45327c332e0dc82aac407f545575e4c1353cac21`

## Production evidence issues

- Issue #68 — production FAILED; SQLite runtime PASS; acceptance öncesi/erken failure evidence.
- Issue #69 — production FAILED; SQLite runtime PASS; gerçek blocker = Official Brick Spread 11 BOS vacancy satırı unresolved.

---

# 12. ÇALIŞMA ORTAMINA DEVİR TALİMATI

Yeni çalışma oturumunda ilk mesaj/iş şu olmalı:

**“`PROJECT_WORK_PROGRESS.md` dosyasındaki 20 Ağustos 2026 checkpointinden devam et. Issue #69’daki Official Brick Spread 11 BOS vacancy eşleşme hatasını merkezi RepresentativeResolver kullanarak düzelt. BOS/BOŞ ayrımını koru, BOSTANCI’yı vacancy yapma, FACT/SUMMARY/prim/P2>P1>IMS davranışına dokunma. Tam testten sonra production acceptance PASS olmadan restart etme.”**

Kodlamaya başlamadan önce kontrol edilecek dosyalar:

- `app/services/official_brick_spread_atomic.py`
- Official Brick Spread'ın gerçek import servis/modülü
- `app/services/representative_resolver.py`
- `app/services/vacancy_matching.py`
- `app/services/ims_import_service.py`
- `app/services/target_import_service.py`
- `verify_ims_acceptance.py`
- `verify_ims_acceptance_extras.py`
- ilgili vacancy/brick spread testleri

**Kritik:** Issue #69 çözülmeden “canlı tamamlandı” denmemeli ve IMS yeni dönem yüklemelerine başlanmamalıdır. Bir sonraki gerçek production acceptance PASS olduktan sonra sistem yeni IMS yüklemelerine açılabilir.
