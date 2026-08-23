# IMS Performance Manager — Kanonik Çalışma / Devir Kaydı

> Son güncelleme: **20 Ağustos 2026, 07:49 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Bu dosya çalışma ortamında devam ederken **tek referans checkpoint** olarak kullanılmalıdır.

---

# 1. ŞU ANKİ DURUM — BURADAN DEVAM ET

IMS import/parser/matching/reconciliation hardening çalışmasının büyük bölümü tamamlandı ve PR #65, #66, #67 `main` branch'e merge edildi. Gerçek production acceptance, sistemi restart etmeden önce kalan vacancy eşleşme problemlerini doğru şekilde yakaladı. Bu nedenle canlı process yeni hardening koduyla yeniden başlatılmadı; mevcut çalışan canlı IMS korunuyor.

## En son `main` commit

- `45327c332e0dc82aac407f545575e4c1353cac21`
- `Merge PR #67: Fix isolated IMS acceptance FACT fingerprint scope`

## Açık production blocker

GitHub Issue **#69 — IMS production deployment FAILED**:

- Commit: `45327c332e0dc82aac407f545575e4c1353cac21`
- Workflow: `32306554405`
- SQLite runtime: **PASS**
  - `journal_mode=wal`
  - `busy_timeout=30000`
  - `integrity=ok`
- Acceptance: **FAIL**
- Hata: `Satış Brick Yayılımı master satırlarında eşleşmeyen temsilci var (11)`
- Görünen örnekler: `ISTANBUL BOS`, `KADIKOY BOS`, `BURSA BOS`, `IZM BOS BRICK`, `ANKARA BOS`, `SAMSUN BOS`, `TRABZON BOS`, `ADANA BOS`, `KONYA BOS`, `ANTALYA BOS`.
- Log toplam 11 satır diyor; issue özetinde 10 isim görünür. 11. isim tahmin edilmemeli, job logundan alınmalı.

**Acceptance fail olduğu için workflow process restart aşamasına geçmedi.**

---

# 2. ISSUE #69 İÇİN AÇILMIŞ GÜNCEL PR #70

PR **#70 — Refresh vacancy resolution after same-import bootstrap** şu anda **OPEN**.

- Branch: `agent/vacancy-cache-official-spread-fix`
- Head: `d9d28e33b722e528ac4601abf286df1a5713b5a0`
- Değişen dosyalar:
  - `app/services/vacancy_matching.py`
  - `tests/test_sqlite_import_resilience.py`

## PR #70 amacı

Gerçek 4. hafta acceptance sırasında explicit `BOS` vacancy satırı, aynı importun BAKİYE/bootstrap aşaması stable Representative slotunu oluşturmadan önce sorgulanabiliyor. Eski global vacancy cache bu ilk `VACANCY_UNRESOLVED` sonucunu sakladığı için slot daha sonra oluşturulsa dahi Official Brick Spread parserı aynı import içinde vacancy'yi yeniden göremiyordu.

PR #70 yaklaşımı:

- unresolved vacancy sonucu cache'lenmesin;
- successful deterministic `BOS/BOŞ` eşleşmesi cache'lenmeye devam etsin;
- bootstrap sonrası aynı import içinde resolver yeniden sorgulandığında stable slot bulunabilsin;
- historic vacancy primary key korunabilsin, yeni duplicate slot oluşmasın.

## PR #70 son CI sonucu — HENÜZ MERGE ETME

GitHub Actions run **#244 / `32307491451`**:

- **238 test collected**
- **236 passed**
- **1 skipped**
- **1 failed**

Başarısız test:

`tests/test_sqlite_import_resilience.py::test_bootstrap_reuses_legacy_vacancy_primary_key_instead_of_creating_duplicate`

Hata:

`TypeError: IMSImportService._region_context() got an unexpected keyword argument 'region_value'`

Kök satır:

`app/services/vacancy_matching.py` içindeki `ensure_vacancy_representative()` fonksiyonu `self._region_context(region_value=..., city=...)` çağrısı yapıyor; fakat mevcut `IMSImportService._region_context()` bu keyword imzasını kabul etmiyor.

**Çalışma ortamındaki ilk iş:** PR #70 branch'inde bu imza uyumsuzluğunu mevcut service sözleşmesine sadık kalarak düzelt. Yeni farklı bir region-context yolu oluşturma. Ardından tam test paketi tekrar çalıştırılmalı.

---

# 3. DEĞİŞTİRİLMEMESİ GEREKEN CANLI BUSINESS KURALLARI

- Production satış kaynağı önceliği: **P2 > P1 > IMS**.
- P1 geldiğinde IMS beklenmez; P2 geldiğinde P1'in yerini alır.
- P2, P1 hiç gelmemiş olsa da final kaynak olabilir.
- Production realizasyonu `%100` üzerinde **kırpılmaz**.
- Nationwide snapshot farklı kaynakları birbirine karıştırmaz.
- Prime engine mevcut payout ve entitlement davranışı korunur.
- Dashboard/region/representative hesapları yeniden tasarlanmaz.
- Hedef business source/schema keyfi değiştirilmez.
- Official NATIONAL/region aggregate kişi toplamıyla ikame edilmez.
- Official Brick Spread FACT/SUMMARY/prim domainine karıştırılmaz; ayrı master side-channel olarak kalır.
- Ana SQLite DB WAL modunda kalır.
- User vault `instance/persistent/users.db` bağımsız korunur.
- Import validation failure durumunda mevcut canlı IMS yayında kalır; yarım veri publish edilmez.

---

# 4. BOS / BOŞ / VACANCY KURALLARI

- `BOS != BOŞ`.
- `DİYARBAKIR BOS != DİYARBAKIR BOŞ` ve ayrı stable Representative ID taşımalıdır.
- `BOS KADRO` ve `BOŞ KADRO` slot kimliğini kaybetmemelidir.
- `BOSTANCI` vacancy değildir.
- `BRICK` tokenı yalnız context olarak kullanılmalıdır; kendi başına vacancy identity değildir.
- Aynı contextte deterministik tek eşleşme yoksa tahmin yapılmamalı.
- Vacancy çözümü başarısız olduğunda accent-insensitive normal alias/fuzzy zincirine geri düşülmemeli.
- Bir BOŞ/BOS slotuna ileride gerçek kişi atansa bile geçmiş IMS kayıtları geriye dönük başka kişiye taşınmamalı; slot identity korunmalıdır.
- Historic `UNASSIGNED...` vacancy primary key varsa canonical code değişikliği yeni duplicate Representative üretmemelidir.

---

# 5. DOSYA/ŞABLON BAĞIMSIZ IMS OKUMA MİMARİSİ

Kullanıcının açık şartı: sistem tek bir örnek Excel şablonuna bağlanmayacak.

Uygulanan yaklaşım:

- sheet adı yalnız yardımcı/fallback sinyaldir;
- sheet sırası business identity değildir;
- header'ın satır konumu sabit değildir;
- kolon sırası sabit değildir;
- content/signature-first discovery kullanılır;
- temsilci/ürün/brick/region + TL/KUTU/PP/target/actual/realization gibi semantik işaretlerden sheet rolü keşfedilir;
- deterministik eşleşme bulunursa otomatik işlenir;
- gerçek anlam belirsizse tahmin etmek yerine FAIL/REVIEW olur.

Ana dosyalar:

- `app/services/workbook_preflight.py`
- `app/services/semantic_import_discovery.py`
- `app/services/workbook_semantic_reconciliation.py`
- `app/services/derived_master_verification.py`

Derived/master eşleşmesi fiziksel `(sheet,row,column)` kimliğine bağlı değildir; semantik key mantığı kullanır. Hücre koordinatı yalnız audit konumudur.

---

# 6. WHOLE-WORKBOOK RECONCILIATION / PR #65

PR **#65 — IMS workbook reconciliation ve vacancy identity hardening** merge edildi.

- Merge: `fdb07136062ad1bb2c59eb5fb4e4a614e82985f3`
- 22 dosya değişti.

Tamamlanan ana katmanlar:

- Whole-workbook manifest ve parser coverage.
- Unknown meaningful sheet blocking.
- Gerçek `0` değerinin data kabul edilmesi (`0 != blank`).
- Content/signature-first renamed sheet discovery.
- Merkezi `RepresentativeResolver`.
- Accent-sensitive vacancy identity.
- Semantic derived/master reconciliation.
- NATIONAL ↔ regions TL/KUTU reconciliation.
- Official Brick Spread atomic side-channel persistence.
- Target ve competition semantic discovery.
- Previous IMS delta audit.
- Manager PASS/FAIL audit report.
- Atomic publish / rollback korunması.
- Production isolated acceptance/fingerprint gate.

Ana servisler:

- `app/services/representative_resolver.py`
- `app/services/vacancy_matching.py`
- `app/services/official_aggregate_service.py`
- `app/services/official_brick_spread_atomic.py`
- `app/services/ims_delta_service.py`
- `app/services/ims_delta_audit.py`
- `app/services/import_result_report.py`
- `verify_ims_acceptance.py`
- `verify_ims_acceptance_extras.py`

PR #65'in son temiz full-suite doğrulamasında:

- **236 test collected**
- **235 passed**
- **1 skipped**
- **0 failed**

Bu pakette P2>P1>IMS, `%100+`, prim, dashboard, auth, SQLite/WAL, user vault, zero metric, renamed sheet, derived conflict, BOS/BOŞ ve BOSTANCI regresyonları geçti.

---

# 7. PR #66 — PRODUCTION DEPLOYMENT EVIDENCE

PR #66 merge edildi:

- Merge: `65a428fcbdb3a8e521dfe56c00685782beb09012`

Amaç:

- production SSH/deploy/acceptance sonucunu yalnız ephemeral Actions logunda bırakmamak;
- deployed SHA ile ilişkili kalıcı GitHub issue evidence üretmek;
- remote failure'ı mask etmeden jobu fail ettirmek.

Issue #68 ilk persistent production evidence kaydıdır. SQLite runtime PASS olduğu halde deployment tamamlanmadı.

---

# 8. PR #67 — ACCEPTANCE FACT FINGERPRINT SCOPE FIX

PR #67 merge edildi:

- Merge: `45327c332e0dc82aac407f545575e4c1353cac21`

Düzeltme:

- `IMSFact` upload-versioned olduğu için acceptance FACT fingerprint artık `upload_id` bazında karşılaştırılır.
- Summary/Target mevcut tasarım gereği period-scoped kalır.
- Bu değişiklik business data/runtime logic değil yalnız acceptance doğrulama aracını düzeltir.

PR #67 tam CI PASS oldu.

---

# 9. GERÇEK 4. HAFTA WORKBOOKU ÜZERİNDE DOĞRULANAN KAYNAK GERÇEKLERİ

Gerçek workbook yalnız sabit şablon olarak değil acceptance/regresyon kaynağı olarak kullanıldı.

Doğrulanan baseline:

- 16 sheet.
- 84.007 gerçek sayısal `0` hücresi; bu nedenle zero handling kritik.
- 113 kişi/kadro.
- Kişi/kadro toplam satış: **125.767.119,32 TL**.
- Kişi/kadro toplam kutu: **1.497.003**.
- Kişi hedef TL toplamı: **137.664.417,843582 TL**.
- Official Brick Spread: **113 x 8 = 904** master kayıt.
- 11 bölge aggregate.
- 11 bölge TARGET TL toplamı NATIONAL ile eşleşiyor.
- 11 bölge cumulative actual TL toplamı NATIONAL ile eşleşiyor.
- 11 bölge cumulative actual KUTU toplamı NATIONAL ile eşleşiyor.
- Ürün bazında resmi target box aggregate'larında NATIONAL ↔ regions uyumu var.

Sonuç: Issue #69 workbook toplam/matematik hatası değil, vacancy resolution lifecycle/cache problemidir.

---

# 10. PRODUCTION DEPLOY GÜVENLİK ZİNCİRİ

`.github/workflows/deploy.yml` production akışı:

1. Full test suite.
2. Production SSH.
3. `git fetch/pull main`.
4. Requirements.
5. Main DB WAL-safe predeploy backup.
6. User vault WAL-safe predeploy backup.
7. Master snapshot before migration.
8. Alembic upgrade.
9. Competition backfill öncesi ek DB backup.
10. Competition backfill.
11. Runtime verification.
12. Target audit.
13. Master snapshot after migration.
14. SQLite WAL / busy_timeout / integrity.
15. Live DB'den `/tmp/ims-acceptance-*` izole online backup.
16. `verify_ims_acceptance.py`.
17. `verify_ims_acceptance_extras.py`.
18. **Yalnız acceptance PASS ise** process restart.
19. `/login` health smoke.
20. Persistent GitHub deployment evidence.

Issue #69'da acceptance FAIL olduğu için process restart yapılmadı.

---

# 11. ÖNCEKİ TAMAMLANMIŞ PROJE ÇALIŞMALARININ KONSOLİDE ÖZETİ

## Competition / import

- Competition import TL/KUTU/TTS/PP kaynaklarına bağlandı.
- Gerçek 24. hafta eski import doğrulamalarında 91.070 competition kayıt işlenmişti.
- RAW → FACT grain aggregation düzeltildi; brick satırlarının birbirini ezmesi engellendi.
- Upload destructive clear varsayılanından güvenli idempotent akışa geçirildi.

## Dashboard / region / representative

- Dashboard aggregate query/payload gerçek veriye bağlandı.
- Representative ve brick global search eklendi.
- Region Performance Center aylık/3/6/yıllık KPI'lara bağlandı.
- Mobile navbar aktif dönem + son IMS + search gösterecek hale getirildi.

## Brick assignment

- Dönemsel `representative_brick_assignments` altyapısı eklendi.
- Manual assignment AUTO ile ezilmez.
- Aynı brickte çoklu temsilci üyeliği desteklendi, FACT çift sayılmaz.
- Eski çalışmada 789 brick / 798 representative-brick membership doğrulandı.

## Target / unit target

- Target ekranı representative accordion'a geçirildi.
- Ortak `target_box_calculation_service.py` ile mevcut onaylı kutu hedef business kuralı merkezileştirildi.

## Prime / Q

- Aylık prim entitlement business kuralları uygulanmış durumda.
- `%100+` uncapped davranışı korunuyor.
- Q dönem analiz ekranı mevcut.

## UI / dark mode

- Login ve dashboard dahil dark mode readability katmanları düzeltildi.
- IMS saatleri Europe/Istanbul gösterimine bağlandı.

## SQLite / user vault

- WAL mode, 30s busy timeout, single-writer coordinator.
- Auth read concurrency korunur.
- User vault ana DB'den bağımsızdır.
- Online WAL-safe backup mevcut.

## Official Brick Spread

- PR #64 merge: `d17c6c70d22e047e2893bed7b469aa206c4f06c7`.
- Official Brick Spread FACT/SUMMARY'den ayrı master side-channel olarak tutulur.

---

# 12. ÇALIŞMA ORTAMINDA ŞİMDİ YAPILACAKLAR

1. **PR #70 branch'inden devam et:** `agent/vacancy-cache-official-spread-fix`.
2. `app/services/vacancy_matching.py` içindeki `_region_context` çağrı imzasını mevcut `IMSImportService._region_context()` sözleşmesiyle uyumlu hale getir.
3. Historic vacancy primary-key reuse testini PASS yap; yeni duplicate slot yaratma.
4. `test_unresolved_vacancy_is_rechecked_after_bootstrap_creates_stable_slot` PASS kalmalı.
5. BOS/BOŞ/BOSTANCI/ambiguous-vacancy testlerinin tamamı PASS kalmalı.
6. Full `pytest tests/ -v`; hedef **0 failure**.
7. PR #70 merge etmeden önce full CI yeşil olmalı.
8. Merge sonrası production workflow çalışsın.
9. İzole gerçek 4. hafta re-import acceptance tüm kapıları PASS etmeli:
   - whole workbook manifest;
   - source/stored reconciliation;
   - manager report PASS;
   - fact/summary/target/competition/official brick spread/official aggregate fingerprints;
   - NATIONAL/regions;
   - BOS/BOŞ stable IDs.
10. Acceptance PASS olmadan production process restart edilmemeli.
11. Health smoke PASS olduktan sonra yeni IMS yüklemelerine başlanabilir.

---

# 13. ÇALIŞMA ORTAMINA VERİLECEK HAZIR DEVAM MESAJI

**“`PROJECT_WORK_PROGRESS.md` dosyasındaki 20 Ağustos 2026 checkpointinden devam et. Öncelik PR #70 (`agent/vacancy-cache-official-spread-fix`). Son CI run #244'te 238 testten 236 passed, 1 skipped, 1 failed. Failure: `test_bootstrap_reuses_legacy_vacancy_primary_key_instead_of_creating_duplicate`; `vacancy_matching.py` içindeki `_region_context(region_value=...)` çağrısı mevcut IMSImportService imzasıyla uyumsuz. Bunu mevcut mimari dışına çıkmadan düzelt. BOS/BOŞ ayrı ID, BOSTANCI normal değer, ambiguity no-guess, historic vacancy PK reuse korunacak. P2>P1>IMS, prime, dashboard, hedef ve %100+ business kurallarına dokunma. Full CI yeşil olmadan merge etme; production acceptance PASS olmadan restart etme.”**

---

# 14. 2026-08-23 — Üretim sonucu Excel’i güvenli otomatik entegrasyon

## Durum: TAMAMLANDI / kullanıcı yüklemesi bekleniyor

- [x] `app/services/production_result_import_service.py`
  - Gerçek KOTA SATIŞ 1./2. üretim şeması için TL ve KUTU sayfaları ayrıştırıldı.
  - Ürün, temsilci ve bölge/boş-kadro eşleşmesi dönem hedef kapsamıyla birebir doğrulanır.
  - Dosya doğrulanmadan hiçbir production sonucu, IMS kaynağı veya hedef satırı yazılmaz.
  - Sonuçların TL hedefi, kutu hedefi, TL çıkışı, kutu çıkışı ve iki realizasyonu kaynak dosyadan ayrı saklanır.
- [x] `ProductionResultService`
  - Görünüm önceliği 2. üretim → 1. üretim → IMS olarak korundu.
  - Üretim kaynağı mevcutsa hesaplar, IMS hedefini ezmeden üretim dosyasındaki nihai hedef/sonuç değerlerini kullanır.
- [x] Migrations
  - `t4i5j6k7l8m9`: exact actual TL/KUTU alanları.
  - `u5j6k7l8m9n0`: production source target TL/KUTU alanları.
  - Sunucuda iki migration da uygulandı; yeni DB oluşturulmadı, mevcut veri silinmedi.
- [x] Gerçek dosya salt-okunur doğrulaması
  - Kaynak: `Tayfun-1 Ocak Realizasyonları 2. Üretim 2026 - KOTA SATIŞ_Fentivag_ (1).xlsx`
  - 113 temsilci/boş-kadro, 791 ürün satırı: kapsam tam eşleşti.
  - Murat Arslan Travazol: 1.005.902 ₺ hedef, 1.323.834 ₺ çıkış, 9.009,10 kutu hedef, 11.856,57 kutu çıkış, %131,61.
  - Dosya **DB’ye uygulanmadı**; kullanıcı IMS Merkezi’nden yükleyecek.
- [x] Test: `8 passed` (production importer, batch priority, business rules).

## Not

- Salt-okunur ön kontrolde 725 ürün-hedef satırı mevcut IMS hedefinden farklı bulundu. Bu dosya içi hata değildir: üretim dosyasının nihai hedefi/sonucu birlikte saklanarak sonuç ekranlarında doğru dönem bazını korur; `targets` ve IMS kaynak verileri değiştirilmez.
- Sunucu servis durumu: `active`.
- GitHub / production commit: `47ecdc7` (son checkpoint öncesi uygulama commitleri: `99b57fb`, `534bbc6`, `c6960fc`, `edad9c9`).

## Sonraki adım

Kullanıcı IMS Merkezi’ndeki **2. üretim** yükleme formundan dosyayı yükler. Form tüm kapsam/doğruluk kontrolleri başarılıysa otomatik uygular; aksi halde veri yazmadan eksik satır/eşleşme nedenini gösterir.

---

# 15. 2026-08-23 — Geçici ve dinamik prim simülasyonu

## Durum: TAMAMLANDI / PRODUCTION AKTİF

- [x] `app/services/simulation_service.py`
  - Simülasyon her hesaplamada en güncel DB verisini salt okunur kullanır.
  - Sonuç önbelleği ve kalıcı JSON geçmiş kaydı devre dışı bırakıldı.
  - Ek kutu, dönemin hedef TL/kutu oranıyla ek satış TL'sine çevrilir; hedefler değiştirilmez.
  - Dinamik sonraki gelişim basamağı, gerekli kutu, ek TL, ürün realizasyonu ve toplam TL realizasyonu hesaplanır.
- [x] `app/templates/simulation.html`
  - Sabit ürün eşik etiketleri kaldırıldı.
  - Ürün tablosuna simüle kutu, simüle TL satış ve realizasyon eklendi.
  - İki tekrar eden alt tablo tek `Dinamik Satış ve Prim Aksiyonları` tablosunda birleştirildi.
- [x] Production gerçek veri testi
  - Murat Arslan / Ocak / Travazol: 11.856,57 + 100 = 11.956,57 kutu.
  - Dönem fiyatıyla geçici TL katkısı: 11.165,52 ₺.
  - Toplam TL realizasyonu: %124,48 → %125,18.
  - Kalıcı history sonucu: 0; sonraki baz hesap tekrar gerçek DB değerinden başladı.
- [x] Test: `15 passed`; login 200, oturumsuz simülasyon 302, servis `active`, journal warning/error yok.
- [x] GitHub / production uygulama commit: `c37a5a7`.
- [x] Temsilci görünümü sadeleştirmesi (`a9fdb7a`): Yönetici Önerileri ve teknik DB ibareleri kaldırıldı; hedef özeti dört KPI oldu; kalan açık/hedef fazlası dinamik ayrıldı. Hedefli test: `16 passed`, production servis `active`.
- [x] Canlı simülasyon (`53ae464`): ek kutu/TL girdileri 450 ms gecikmeyle otomatik hesaplanır, devam eden istekte son değişiklik sıraya alınır; Ana Prim tekrar kartı kaldırıldı. Production +386 Monurol testi: ürün %76,83→%90, toplam TL %124,48→%126,60, prim 60.000→62.500 ₺. Test: `16 passed`.
- [x] Canlı sonuç ve seçim sırası düzeltmesi (`b3bbf71`, `9ec0b9e`): atanmamış/boş temsilciler seçim listesinin sonuna taşındı; tekrar eden Quarter kartı kaldırıldı; eski HTTP yanıtının yeni simülasyonu ezmesi `AbortController` ve istek sürümüyle engellendi.
- [x] Ek kutunun TL etkisi düzeltildi: delta modunda formun sıfır TL alanı otomatik dönem fiyatlamasını artık bastırmıyor. Production gerçek route testi (Murat Arslan / Ocak / +400 Monurol / +8 Mixovul): gerçekleşen 1.981.806,33 ₺ → 2.017.861,04 ₺, realizasyon %124,48 → %126,75, prim 60.000 ₺ → 62.500 ₺; Monurol %90,48 ve Mixovul %95,71. Test: `25 passed`; servis `active`.
- [x] Prim basamağı tam yüzde yuvarlaması: ondalık kısım yalnızca ,50'yi aşarsa üst tam sayıya çıkar; %129,49/%129,50 = 62.500 ₺, %129,51 = 65.000 ₺, %135 = 67.500 ₺, %140 = 70.000 ₺.

## Sonraki adım

Kullanıcı simülasyon ekranında farklı temsilci/ürün kutu senaryolarını görsel olarak doğrulayabilir; hesaplamalar sayfa dışına taşınmaz ve DB'ye yazılmaz.

---

# 16. 2026-08-23 — Bölgesel rakip ve pazar analiz merkezi

## Durum: TAMAMLANDI / PRODUCTION AKTİF

- [x] `app/services/region_market_service.py`
  - Her temsilciyi ayrı ayrı sorgulamak yerine bölge kodu üzerinden tek toplulaştırılmış rekabet sorgusu kullanır.
  - Seçili dönemin son tamamlanan IMS yüklemesindeki aylık rekabet kutu kayıtlarını şirket/rakip/brick/ürün bazında ayırır.
  - Nihai üretim sonucu varsa bölgenin resmi şirket kutu çıkışını ve hedefini P2 > P1 > IMS önceliğiyle kullanır; kaynak tabloları değiştirmez.
  - 60 saniyelik upload-kapsamlı önbellek, eşzamanlı bölge yöneticisi okumalarında CPU ve SQLite yükünü sınırlar.
- [x] `app/templates/region_performance.html`
  - AI Performans Rehberi'nin üstüne Bölgesel Rekabet ve Pazar Merkezi eklendi.
  - Dikey ürün seçimi masaüstünde, yatay kaydırmalı seçim mobilde çalışır.
  - 7 ürün için hedef kutu, şirket/rakip çıkışı, hedef realizasyonu, pazar payı ve rakip ürün dökümü gösterilir.
  - Rakip baskısı yüksek ilk 10 brick ayrıca listelenir.
- [x] Test ve production doğrulaması
  - Yeni hedefli testler: `2 passed`; mevcut route paketi: `49 passed`.
  - 101, 201, 301, 401, 501, 601, 602, 701, 801, 802 ve 901 sayfaları oturumlu gerçek DB ile HTTP 200 ve panel render PASS.
  - 11 bölgenin tamamında 7 ürün ve gerçek şirket/rakip kutu verisi mevcut.
  - 11 bölgenin soğuk toplu hesabı 5,22 sn; önbellekli toplu tekrar 0,02 sn.
  - Servis `active`; mevcut DB üzerinde silme/reset/migration yapılmadı.
- [x] GitHub / production commitleri: `d5fdbf8`, `3335e4a`.

## Sonraki adım

Bölgesel analizlerin aynı doğrulanmış veri sözleşmesiyle Türkiye Pazar Analizi ekranında birleştirilmesi.
