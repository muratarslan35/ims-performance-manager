# IMS Performance Manager — Çalışma Checkpointi

## Q period premium dashboard (2026-08-10)

- [x] `app/services/prime_engine.py` — Monthly payments are mutually exclusive: 20,000 TL ciro premium for total TL >=100% without product eligibility, or main premium for eligible product performance. Main premium is 50,000 TL at 100%, +2,500 TL per 5 points, capped at 70,000 TL at 140%.
- [x] `app/services/quarter_entitlement_service.py` — Read-only Q report combines monthly gross premiums with four-main-product 75/90/100 TL and unit carry balances.
- [x] `app/routes/__init__.py`, `app/templates/quarter.html`, `app/templates/partials/sidebar.html` — `/quarter` is now a dedicated Q Dönem Analizi screen in the sidebar.
- [-] Targeted production checks PASS: %110=55,000 TL; %140=70,000 TL; ciro at %100=20,000 TL; Q service and template render passed. `/quarter` login redirect returns 302 and the server is listening on port 8000.
- [x] Commit/deploy: `e8f2ae8` pushed and deployed.

## Mobile continuation and deploy automation (2026-08-11)

- [x] `.github/workflows/deploy.yml` — Main branch pushes can deploy through GitHub Actions after the SSH secret is configured.
- [x] `docs/MOBILE_CONTINUATION.md` — Mobile session handoff, non-secret server variables, deployment contract and current Q premium commits are documented.
- [!] GitHub secret `IMS_DEPLOY_SSH_KEY` still requires one manual repository-settings action. The private `bist.key` is intentionally not tracked in Git.

## Representative code follow-up (2026-08-09)

- `app/services/ims_import_service.py` no longer creates `AUTO-` representative codes. New master codes are derived from the normalized Excel name, for example `ENGIN YAPAK` -> `ENGINYAPAK`.
- Targeted syntax validation passed and the active source contains no `AUTO-` code-generation path.
- Real representative/region/city/brick coverage and dashboard-map/AI verification remain blocked until the Flask/SQLAlchemy/pandas/openpyxl runtime can be installed and `instance/ipm.db` can be created.

## Runtime validation checkpoint (2026-08-09)

- The user explicitly authorized creating a new, deployment-compatible `instance/ipm.db` and running real import/smoke tests.
- The application dependencies were requested from `requirements.txt`, but installation stopped with `OSError: [Errno 28] No space left on device`.
- The temporary, incomplete `.venv` uses approximately 49 MB and contains no usable Flask runtime. Its removal was explicitly approved, but the environment's deletion policy rejected the deletion command.
- No new database was created. This avoids handing off an incomplete schema that would not be server-compatible.
- No workbook, application data, source tables, or existing DB was modified during this failed runtime setup.

### CURRENT BLOCKER

Free local disk space (and allow removal of the temporary `.venv`, if still present), then install `requirements.txt` and resume from the runtime validation stage. The next steps are: run Alembic migration into `instance/ipm.db`, import the 24th-week workbook, compare workbook/DB counts and IDs, then smoke-test all authenticated menus and dashboard/AI payloads.

## Latest checkpoint (2026-08-09)

### FILE: `app/models.py`

- STATUS: COMPLETE
- CHANGE: Added read/write compatibility aliases from `Target.target_unit` and `Target.target_tl` to the persisted `unit_target` and `tl_target` columns. Added the ManualMatchQueue status/entity constants referenced by matching and alias logic.
- TEST: Targeted `py_compile` plus full `compileall` scan of `app`, `tests`, and `migrations`.
- RESULT: PASS.
- NEXT: DB-backed targets and matching smoke tests.

### FILE: `app/routes/settings.py`

- STATUS: COMPLETE
- CHANGE: `ensure_prime_settings()` now supplies the required `category="Prim"` value when inserting defaults.
- TEST: Targeted `py_compile` plus full source syntax scan.
- RESULT: PASS.
- NEXT: Run against the existing SQLite schema.

### FILE: `app/services/ims_import_service.py`

- STATUS: COMPLETE
- CHANGE: Competition import runs only when all of its required sheets exist, so ordinary IMS uploads remain safe. The supplied 24th-week workbook contains all supported competition sheets.
- TEST: Targeted `py_compile` plus full source syntax scan.
- RESULT: PASS.
- NEXT: Validate inserted, duplicate, and invalid counts with the existing DB.

## Pending blockers

1. `instance/ipm.db` is not present anywhere in this local project folder. The protocol forbids creating another DB, so migrations, real import, SQL integrity checks, and HTTP smoke tests cannot be run safely.
2. The local Python environment lacks the application runtime packages (Flask, SQLAlchemy, pandas, openpyxl), and package download is unavailable. Runtime tests cannot be run in this environment.

## Last completed stage

Known targets/matching/settings errors and the competition-import missing-sheet safeguard are complete. Dashboard V3 was checked statically; its runtime payload remains blocked by the missing DB/runtime.

## Last completed file

`app/services/ims_import_service.py`

## Next file/stage

When the existing `instance/ipm.db` and a usable local dependency environment are available in this same project folder: inspect migration state read-only, then run the real 24th-week import, SQL coverage/FK checks, and authenticated route smoke tests.

## Proje durumu

- Çalışma alanı: Bu yerel klasör. Uzak Git/GitHub işlemleri bu aşamada devre dışıdır.
- Gerçek IMS kaynağı: `Tayfun-1 24.Hafta Haziran Brick Analizi_.xlsx`.
- Excel ilk envanteri: 16 sheet; ana satış/özet sayfaları ile aylık-haftalık TL/KUTU ve pazar/rekabet verileri içerir.
- Veritabanı: `instance/ipm.db` varlığı henüz doğrulanacak. Yeni DB oluşturulmayacak, mevcut DB silinmeyecek veya resetlenmeyecek.

## İncelenen dosyalar

- [x] `app/models.py`
- [x] `app/services/ims_import_service.py`
- [x] `app/services/competition_import_service.py`
- [x] `app/ims_importer.py`
- [x] `app/ims.py`
- [x] `app/__init__.py`
- [x] `app/routes/settings.py`
- [x] `app/routes/targets.py`
- [x] `app/routes/matching.py`
- [x] `app/services/dashboard_service.py`
- [x] `app/templates/dashboard.html`
- [x] `app/static/js/dashboard.js`
- [x] `migrations/versions/`
- [x] `tests/test_ims_import_service.py`
- [x] `tests/test_database_migrations.py`

## Tamamlanan dosyalar

### DOSYA: `app/ims_importer.py`

- DURUM: TAMAMLANDI
- YAPILAN: Hatalı `brick` alanı ataması düzeltildi; modülün import edilmesini engelleyen eşleşmeyen parantez kaldırıldı.
- TEST: Python sözdizimi taraması.
- SONUÇ: PASS.
- KALAN: Bu eski/alternatif orchestrator'ın ana upload akışında kullanılmadığı import bütünleştirmesi sırasında doğrulanacak.

### DOSYA: `app/query/base_query.py`

- DURUM: TAMAMLANDI
- YAPILAN: Modül başındaki eksik docstring açılışı düzeltildi.
- TEST: Python sözdizimi taraması.
- SONUÇ: PASS.

### DOSYA: `app/query/dashboard_query.py`

- DURUM: TAMAMLANDI
- YAPILAN: Modül başındaki eksik docstring açılışı düzeltildi.
- TEST: Python sözdizimi taraması.
- SONUÇ: PASS.

### DOSYA: `app/query/filters.py`

- DURUM: TAMAMLANDI
- YAPILAN: Modül başındaki eksik docstring açılışı düzeltildi.
- TEST: Python sözdizimi taraması.
- SONUÇ: PASS.

## Tamamlanan dosyalar (devam)

### DOSYA: `app/services/ims_import_service.py`

- DURUM: TAMAMLANDI
- YAPILAN: `CompetitionImportService` ana import transaction'ına bağlandı; competition inserted/duplicate/invalid sayaçları import istatistiklerine eklendi.
- TEST: Hedefli derleme + `app`, `tests` ve `migrations` sözdizimi taraması.
- SONUÇ: PASS.
- KALAN: Mevcut SQLite DB bulununca gerçek Excel importu ile kayıt kapsamı doğrulanacak.

### DOSYA: `app/ims.py`

- DURUM: TAMAMLANDI
- YAPILAN: Upload rotasının yıkıcı `clear_before_import=True` davranışı güvenli varsayılan olan `False` olarak düzeltildi.
- TEST: Hedefli derleme + çağrı denetimi.
- SONUÇ: PASS.

### DOSYA: `app/__init__.py`

- DURUM: TAMAMLANDI
- YAPILAN: Competition API blueprint'i uygulama kayıt zincirine eklendi.
- TEST: Hedefli derleme + blueprint kaydı denetimi.
- SONUÇ: PASS.

### DOSYA: `migrations/versions/d2f4c8a9b6e1_add_competition_data.py`

- DURUM: TAMAMLANDI
- YAPILAN: Mevcut veriyi silmeden `ims_competition_data` tablosunu, FK/unique constraint ve sorgu indekslerini oluşturan idempotent migration eklendi.
- TEST: Hedefli derleme + migration kaynak sözdizimi taraması.
- SONUÇ: PASS.

## Tespit edilen hatalar

1. Yerel SQLite DB henüz bulunup doğrulanmadı.

## Çözülen hatalar

- Dört Python sözdizimi hatası düzeltildi (`ims_importer.py` ve üç query modülü).
- Rekabet import zinciri, API blueprint'i, migration-first şema ve güvenli upload varsayılanı tamamlandı.

## Excel import durumu

- Sheet sayısı: 16.
- Önemli rekabet sheet'leri: `AYLIK REKABET TL`, `AYLIK REKABET KUTU`, `HAZİRAN TL`, `HAZİRAN KUTU`, `TL`, `KUTU`, `PAZAR`.
- Sonraki adım: mevcut SQLite DB üzerinde gerçek import öncesi kapsam sayımı ve migration durumunu salt-okunur doğrulamak.

## Test durumu

- Python kaynak sözdizimi: PASS (dört hata düzeltildikten sonra).
- Uygulama/test bağımlılıkları: yerel runtime içinde henüz kurulu değil; paket indirme erişimi başarısız oldu. Alternatif yerel ortam/önbellek aranacak, yeni DB oluşturulmayacak.

## Son tamamlanan aşama

Rekabet importunun kaynak, route ve migration bağlantıları tamamlandı.

## Sonraki yapılacak aşama

`instance/ipm.db` konumunu ve migration durumunu doğrula; ardından yalnızca gerekli import/migration/route bağlarını nokta atışı düzelt.

---

## 2026-08-09 — Import performance checkpoint

### DOSYA: `app/services/competition_import_service.py`

- DURUM: TAMAMLANDI
- YAPILAN: Gerçek Excel'deki `AYLIK REKABET TL`, `AYLIK REKABET KUTU`, `TTS Rekabet` ve `TTS Rekabet PP` şeması desteklendi. Rastgele `ReadOnlyWorksheet.cell()` erişimi kaldırılıp sayfa başına tek-geçişli değer önbelleği eklendi; import dönemi yıl/ay için otorite kabul edildi.
- TEST: Dört rekabet sayfası gerçek Excel üzerinde ayrıştırıldı; 91.070 kayıt tek importta yazıldı.
- SONUÇ: PASS. Tam import süresi 24,3 saniye.

### DOSYA: `app/services/target_import_service.py`

- DURUM: TAMAMLANDI
- YAPILAN: `TTS ÇIKIŞLARI` içindeki başlıksız kompakt `HAZİRAN HEDEF` düzeni için hedefli ayrıştırıcı eklendi.
- TEST: Gerçek çalışma kitabında 42 temsilci-ürün hedefi üretildi ve summary hedeflerle yeniden kuruldu.
- SONUÇ: PASS.

### DOSYA: `app/services/ims_import_service.py`

- DURUM: TAMAMLANDI
- YAPILAN: Rekabet importuna upload yılı, ayı ve hafta numarası iletiliyor; bulk RAW yazımı korunuyor.
- TEST: 24. hafta gerçek Excel importu.
- SONUÇ: PASS.

## Excel import durumu

- Kaynak: `Tayfun-1 24.Hafta Haziran Brick Analizi_.xlsx` (16 sheet).
- Upload: 1; süre: 24,3 saniye.
- RAW: 8.118; Fact: 1.087; Summary: 594; Competition: 91.070; Representatives: 99; Products: 6; Targets: 42.
- Rekabet dağılımı: Aylık KUTU 45.090, Aylık TL 45.090, TTS Rekabet 450, TTS Rekabet PP 440.
- FK kontrolleri: RAW/Fact/Summary için temsilci ve ürün yetim kaydı 0; `AUTO-` rep_code 0.

## Son tamamlanan aşama

Faz 1: gerçek Excel importu, hedef importu, rekabet importu ve temel veri bütünlüğü doğrulaması tamamlandı.

## Sonraki yapılacak aşama

Faz 2: ID/eşleştirme ayrıntıları ve hedefli dashboard/route/AI gerçek payload smoke testleri. Önce dashboard veri sözleşmesi incelenecek; tamamlanmış import tekrar çalıştırılmayacak.

### 2026-08-09 — Dashboard veri akışı denetimi ve düzeltmesi

### DOSYA: `app/services/ims_import_service.py`

- DURUM: TAMAMLANDI
- SORUN: Birleştirilmiş Excel üst başlıklarındaki TL/KUTU bilgisi ürün kolonlarına aktarılmadığı için satış TL alanı sıfırdı. Aynı temsilci/ürün için birden çok brick satırı Fact'e yazılırken son satır öncekileri eziyordu.
- YAPILAN: Başlık grupları dinamik olarak yatay taşındı; TL/KUTU semantiği Excel ay/hafta ifadesinden otomatik çözülüyor. RAW satırları Fact grain'inde toplanarak UPSERT ediliyor.
- TEST: Gerçek 24. hafta dosyasıyla izole import PASS: 8.849 RAW, 1.186 Fact, 594 Summary, 91.070 Competition; Fact TL toplamı 66.778.367,82.

### DOSYA: `app/query/dashboard_query.py`, `app/services/dashboard_service.py`, `app/builders/dashboard_payload_builder.py`

- DURUM: TAMAMLANDI
- YAPILAN: Global dashboard artık temsilci id=0 ile boş PrimeEngine çağrısı yapmıyor; aggregate query ile KPI ve ürün kartlarını üretiyor. Pazar payı trendi `ims_summary` yerine PP rekabet kaynağından okunuyor. AI domain alanları V3 `ai_*` payload contract'ına null-safe eşleniyor. Top temsilci hedef join'i dönem+ürün grain'ine daraltıldı.
- TEST: Gerçek DB payload: satış 66.778.367,82 TL; altı ürün dolu; PP trendi %33,88; AI alanları tip doğru; brick özeti 789 AUTO. `dashboard.html` render PASS (58.236 byte).

## Excel import durumu (son)

- Kaynak: `Tayfun-1 24.Hafta Haziran Brick Analizi_.xlsx`; 16 sheet.
- Mevcut DB'ye veri silmeden ikinci import uygulandı: upload=2, 8.849 yeni RAW denetim kaydı, 1.087 Fact update + 99 insert, 594 Summary, 91.070 rekabet kaydı.
- Yedek: `backups/ipm_before_dashboard_data_fix_20260809_*.db`.
- Hedef verisi uyarısı: Bu Excel'de ayrı hedef sheet'i yoktur. DB'deki 42 eski hedef satırı toplam 1.926,45 TL olduğundan 66,8M satışla aynı ölçekte değildir; hedef/gerçekleşme yüzdeleri karar desteği için kullanılmamalıdır. Kaynak hedef dosyası sağlanmadan hedef değeri tahmin edilmemelidir.

## Son tamamlanan aşama

Faz 2 dashboard veri kaynağı, import aggregation ve AI payload contract düzeltmesi tamamlandı.

## Sonraki yapılacak aşama

Değişiklikleri Git commit/push ve sunucu deploy'una aktar; uygulama başlatıldıktan sonra oturumlu tarayıcıyla dashboard menü/Chart.js görsel smoke testini tamamla. Ayrı hedef kaynak dosyası geldiğinde 42 eski hedef satırını ilgili dönem için upsert et.

### 2026-08-09 - Target box value correction

- [x] `app/services/ims_import_service.py` - Removed the derived `TL target / unit price` box-target calculation. The current workbook provides TL targets only; it does not contain a box-target field.
- [x] `app/routes/targets.py` and `app/templates/targets.html` - Targets now render as one collapsed row per representative. Opening a representative shows that person's product-level TL targets; opening another closes the previous row.
- [x] `app/static/css/style.css` - Added the scoped accordion presentation; the old flat target table is hidden.
- [x] Server DB correction - In one SQLite transaction, reset only 2026/06 derived `targets.unit_target` and `ims_summary.target_unit` values to zero; no rows were deleted and TL target total remains 131,153,092.33.
- [x] Server validation - Python compilation passed; authenticated target-route render returned HTTP 200 and includes the accordion/source label without the former fabricated box figure.
- Commit/deploy: `71dd358 fix(targets): preserve source box targets and group rep goals` pushed and pulled on the server.

## Son tamamlanan aşama

Target box value correction and representative accordion deployment completed.

## Sonraki yapılacak aşama

If a workbook containing an explicit box target is supplied, map that source column to `Target.unit_target`; until then leave it as unavailable rather than deriving it from the product price.

### 2026-08-09 - Approved box-target calculation rule

- [x] Decision updated: box targets are intentionally derived from the approved product price master: `unit_target = tl_target / product.unit_price`, rounded to two decimals.
- [x] `app/services/target_box_calculation_service.py` - Added one shared, transaction-safe calculation service for `targets.unit_target` and the linked `ims_summary.target_unit`.
- [x] `app/services/ims_import_service.py` - BAKIYE imports now apply the shared formula after each TL target is read.
- [x] `app/routes/targets.py` / `targets.html` - Added the protected "Kutu Hedeflerini Hesapla" action and shows the persisted calculated box value in each collapsed representative row.
- [x] Server data - 594 targets recalculated; missing product price=0, target formula mismatch=0, summary formula mismatch=0, total unit target=1,185,398.56.
- [x] Server route render - HTTP 200; accordion, calculation action and formula note present.
- Commit/deploy: `5c06c5e feat(targets): calculate persisted box targets from prices` pushed and deployed; application restarted.

### 2026-08-09 — Dinamik dosya şeması düzeltmesi

- `CompetitionImportService` artık belirli aylara veya sabit sayfa listesine bağlı değildir; `REKABET` etiketi ve TL/KUTU/PP semantiğiyle sayfaları dinamik seçer.
- `IMSImportService` upload oluşturmadan önce Excel üst bilgisinden ayı algılar; formdaki ay farklıysa Excel dönemi kullanılır.
- Hedef tablosu, sayfa adı yerine `HEDEF/TARGET` başlığı ve gerçek ürün eşleşmelerinden algılanır; `BRICK REA.` gibi yanlış pozitifler dışarıda kalır.
- Test: gerçek Excel'de ay=6 algılandı, hedef sayfası=1 ve hedefli Python derlemesi PASS.

### 2026-08-09 — Dönemsel temsilci/brick altyapısı

- `representative_brick_assignments` tablosu migration-first olarak eklendi. Aynı brick için yıl/ay başına tek sorumlu temsilci kuralı uygulanır; `MANUAL` atamalar importun `AUTO` güncellemesiyle ezilmez.
- Yeni RAW importları brick/territory/province boyutlarını saklar ve import sonunda otomatik brick ataması üretir.
- Temsilci detay route'u ve ayar ekranı eklendi: `/representatives/view/<id>` içinde dönemsel brick listesi ve manuel `Brick Ata / Devral` işlemi var.
- Migration head: `g2b3c4d5e6f7`; hedefli Python derleme PASS.
- Not: Mevcut 24. hafta RAW kayıtları eski şema ile brick bilgisi saklanmadan yazılmıştır. Yeni atamaların otomatik oluşması bir sonraki Excel importunda başlayacak; geçmiş kaydı veri silmeden yeniden eşlemek ayrı bir backfill adımıdır.

### 2026-08-09 — Brick backfill ve Faz 2 başlangıcı

- Gerçek 24. hafta Excel'i yeniden satış/fact yazmadan okunarak 789 brick–temsilci ataması backfill edildi.
- Dashboard gerçek payload testi iki hatayı ortaya çıkardı ve düzeltti: eşleştirme sayaçları olmayan `status` alanını sorgulamayacak; `RecoveryEngine.get_product_data()` uygulandı.
- Doğrulama: aktif dönem 2026/6, temsilci=99, upload=1, top_representatives=10; DashboardService payload üretimi PASS.

### 2026-08-09 — Brick atamalarının dashboard bağlantısı

- DashboardRepository → DashboardService → DashboardPayloadBuilder → dashboard.html zincirine aktif dönem brick atamaları eklendi.
- Gerçek payload sonucu: toplam=789, manuel=0, otomatik=789. Kart temsilci ayarlarına yönlendirir.
- Gerçek payload ile template render testi PASS; hedefli Python derleme PASS.

### 2026-08-09 — Faz 2 SQL veri bütünlüğü

- FK denetimi: RAW/Fact/Summary/brick assignment temsilci ve ürün yetimleri 0.
- Rep kodu: `AUTO-`=0, boş kod/ad=0. Üç kod uzunluk nedeniyle adın tam normalize edilmiş biçiminden kısadır; çakışma değildir.
- Rekabet: 91.070 kayıt; TL=45.090, KUTU=45.090, TTS=450, PP=440; boş bölge/brick ve dönem uyumsuzluğu 0.
- 789 assignment brickinin tamamı CompetitionData brickiyle birebir eşleşti. Atamalar kodlu bölge/il ile backfill edildi; 789/789 kodlu bölge, 789/789 il, 99/99 temsilci ili dolu.
- Bölge kodları Excel kaynaklıdır: 101, 201, 301, 401, 501, 601, 602, 701, 801, 802, 901. Dönem–brick duplicate=0.

### 2026-08-09 — Aylık prim hakedişi kapısı

- [x] `app/services/prime_engine.py` — Aylık prim kuralı ürün adına sabitlenmeden tanımlandı: dört ana ürünün tamamı en az %75, en az üçü %90 ve üzeri; ayrıca toplam TL realizasyonu en az %100 olmalıdır.
- [x] Prim/ciro/bonus/recovery/ürün bileşenleri bu aylık hakediş kapısı sağlanmadığında ödeme üretmez. Ayar değişiklikleri eski cache sonucu kullanılmadan her hesap motoru oluşturulduğunda yeniden okunur.
- [x] `app/routes/settings.py` — Eksik prim ayarları `category="Prim"` ile oluşturulur; zorunlu kategori hatası giderildi.
- [x] Uyumluluk — Eski `app.prime_engine` sarmalayıcısının kullandığı `_cache_clear` geri eklendi.
- [x] Test — Sunucu venv üzerinde `tests.test_prime_engine_service`: 65/65 PASS.
- [x] Gerçek Haziran verisi — Aktif dört ana ürün Travazol, Monurol, Mixovul, Acnemix olarak doğrulandı. Örnek temsilcilerde toplam TL %42,38–%70,39 aralığında ve en az bir ürün %75 altında olduğu için aylık hakediş doğru biçimde oluşmadı.
- [x] Commit/deploy — `48c1add`, `cb3ae71`, `f08433b`, `e310c5f` GitHub'a gönderildi ve sunucuya çekildi; uygulama `/login` HTTP 200 ile çalışıyor.

## Son tamamlanan aşama

Aylık dört ürün + toplam TL prim hakedişi kuralı üretime alındı.

## Sonraki yapılacak aşama

Üç aylık Q dönemi için aynı esnek ürün kuralının üç aylık kümülatif hedef/gerçekleşen verisine nasıl uygulanacağı ve Q ödemesinin aylık ödemeden bağımsız katsayı/tutar sözleşmesi netleştirildikten sonra uygulanacak. Mevcut Haziran verisinde Q2'nin Nisan ve Mayıs verileri bulunmadığından dönem tamamlanmadan Q hakedişi üretilmemelidir.

### 2026-08-10 — Dashboard kabuğu ve temsilci arama akışı

- [x] `app/__init__.py` — Navbar için aktif IMS dönemi ve son tamamlanan yükleme context'i eklendi; üst kartlar artık boş değildir.
- [x] `sidebar.html`, `navbar.html`, `shell-enhancements.css` — Orijinal Bilim İlaç görseli açılmış sol menüde ve menü kapalıyken üst navbar'da konumlandı.
- [x] `global-search.js`, `representatives.py` — Üst arama gerçek temsilci ve brick sonuçlarını getirir, seçimi dönemsel temsilci performans ekranına yönlendirir.
- [x] `representative_detail.html` — Temsilci bazında TL/kutu hedefi, IMS gerçekleşeni, realizasyon ve brick kapsamı birlikte gösterilir.
- [x] `layout.js` — Sağ üst kullanıcı menüsü Bootstrap CDN durumundan bağımsız açılır; profil, şifre, bölge ve çıkış bağlantıları kullanılabilir.
- [x] Test: sunucu venv üzerinde auth/search regresyonu 12/12 PASS. Canlı doğrulama: `SERKAN OZGU` araması `/representatives/view/30?year=2026&month=6` ekranına yönlendi; kullanıcı menüsü açıldı; aktif dönem `2026/06 · 24 . Hafta`, son IMS `09.08.2026` göründü.
- [x] Commit/deploy: `900c21b`, `be05f0d`, `fe3b7a6` GitHub'a gönderildi ve güncel Flask süreci ile yayına alındı.

### 2026-08-09 — Ortak brick üyeliği ve uzun temsilci adları

- `representative_brick_assignments` tek sorumlu kuralı migration-first olarak çoklu üyelik kuralına çevrildi: benzersizlik artık `yıl + ay + brick + representative_id` düzeyinde.
- Gerçek Excel’de iki geçerli TTS adı taşıyan 9 brick bulundu. Satış/fact yalnızca birincil satış sahibi üzerinden hesaplanmaya devam eder; ikinci kişi ayrıca aynı brickin üyesi olarak saklanır ve çift sayım yapılmaz.
- Backfill sonucu: 789 benzersiz brick, 798 temsilci–brick üyeliği. Örnek `ADANA AKINCILAR+KISLA`: MERT HIKMET DAG ve GOKHAN ONAL; `IZM BAYRAKLI`: YIGIT PLAV ve SUDE OZBAYKAL.
- Uzun ad doğrulaması: Excel’deki 99 geçerli temsilcinin tamamı master ID ile eşleşti; eşleşmeyen yok. En uzun ad `MUHAMMET ALPARSLAN SAFAK` (24 karakter); rep_code çakışması veya `AUTO-` prefix yok.
- Migration head: `h3c4d5e6f7a8`; Python derleme ve gerçek DB backfill PASS.
