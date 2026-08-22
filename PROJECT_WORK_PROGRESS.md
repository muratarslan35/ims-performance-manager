# IMS Performance Manager — Kanonik Çalışma / Devir Kaydı

> Son güncelleme: **22 Ağustos 2026, 22:14 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Bu dosya çalışma ortamında devam ederken **tek referans checkpoint** olarak kullanılmalıdır.

---

# 1. ŞU ANKİ DURUM — BURADAN DEVAM ET

Sistem production'da aktif ve son doğrulanmış sürüm başarılıdır.

## En son production `main` commit

- `70562d85f25b82dda8d1cf370dfabf09d891659b`
- PR #141: SQLite uzun dönem ölçekleme / +49 IMS kapasite koruması.
- Production evidence: **Issue #142 — IMS production deployment SUCCESS**.
- Workflow run: `32568027184`.

## Production runtime

- Oracle Cloud / Frankfurt (`eu-frankfurt-1`).
- Mevcut host: `130.162.48.162`.
- Ubuntu 22.04.
- SSH port: 22.
- Uygulama portu: 8000.
- App path: `/home/ubuntu/ims_system`.
- Service: `ims-performance-manager.service`.
- Gunicorn/systemd aktif.
- CPU_COUNT: 2.
- RAM: yaklaşık 956 MB (~1 GB).
- Swap: 2 GB.
- Root disk: yaklaşık 49 GB.
- Kullanılan: yaklaşık 13 GB.
- Boş: yaklaşık 36 GB.
- `/login` production health: PASS.

## Current operational decision

- **Mevcut Oracle Free production sunucusunda devam edilecek.**
- Frankfurt'ta yeni `VM.Standard.A1.Flex` denendi ancak AD1/AD2/AD3'te `Out of capacity` alındı.
- 2 OCPU / 12 GB RAM denendi; 1 OCPU / 6 GB da kapasite bulamadı.
- Eski production instance silinmedi.
- Ücretli shape'e geçilmedi.
- A1 kapasitesi ileride açılırsa migration paralel yapılacak; eski production yeni makine tam PASS olmadan kapatılmayacak.

---

# 2. DB STRATEJİSİ — SON KARAR

Kullanıcı 5–10 yıllık IMS geçmişini saklamak istiyor ve ileride Oracle ücretli sunucuya geçebilir.

## Karar

**Şimdilik tek `ipm.db` ile devam et. Yıllık SQLite DB shard mimarisine geçme.**

Gerekçe:

- Kritik sorgular artık `upload_id`, dönem, temsilci, ürün ve brick bazında scope edilip kompozit indekslerle çalışıyor.
- Milyonlarca satır olması tek başına ekranların lineer yavaşlaması anlamına gelmiyor.
- Yıllık `ims_2026.db`, `ims_2027.db` yaklaşımı cross-year sorgu, migration, backup, router, transaction ve operational complexity getirir.
- Mevcut sistem tek DB ile +49 IMS için production kapasite kapısından PASS geçti.
- İleride ücretli sunucuya geçilirse aynı DB dosyası daha güçlü CPU/RAM/storage üzerine taşınabilir; veri bölmek zorunlu değil.
- 5–10 yıllık dönemde gerçek concurrency / WAL / backup / latency sınırına yaklaşılırsa **yıllık SQLite parçalamak yerine PostgreSQL migration** daha profesyonel uzun vadeli seçenek olarak değerlendirilecek.

## Yaklaşık büyüme

Production projeksiyonunda +49 IMS:

- aktif DB'ye tahmini +3,152,501,753 byte (~3.15 GB decimal) ek büyüme;
- competition +4,888,044 satır;
- raw +1,437,219 satır;
- fact +155,036 satır.

Aynı veri yoğunluğu uzun yıllar sürerse kaba aktif DB büyüklüğü:

- 1 yıl: ~3–4 GB;
- 5 yıl: ~15–20 GB;
- 10 yıl: ~30–40 GB.

Bu seviyeler SQLite için tek başına problem sayılmaz; asıl karar kriterleri sorgu p95, WAL contention, import sırasında kullanıcı beklemeleri, backup/integrity süreleri ve disk/RAM baskısıdır.

---

# 3. PR #141 — SQLITE UZUN DÖNEM ÖLÇEKLEME

PR #141 production'a alındı ve Issue #142 SUCCESS.

## Uygulananlar

- SQLite WAL korunuyor.
- `busy_timeout=30000` korunuyor.
- Kontrollü SQLite connection cache / mmap / temp-store optimizasyonları eklendi.
- Başarılı IMS import sonrası düşük etkili:
  - `PRAGMA optimize`
  - `wal_checkpoint(PASSIVE)`
- Otomatik full `VACUUM` yok; canlı sistemi bloklamamak için bilinçli olarak kullanılmıyor.
- FACT / summary / target / upload historical read path'lerine kompozit indeksler eklendi.
- Competition/raw mevcut güçlü indeksleri korundu.
- Her production deploy'da:
  `database_capacity_audit.py --additional-uploads 49 --optimize`
  çalışıyor.
- Kritik query plan full table scan'e dönerse deployment fail-closed.

## Production +49 IMS capacity sonucu

Issue #142 `DB_CAPACITY`: **PASS**.

- Active DB bytes: `201682944` (~192 MiB).
- Additional uploads projected: `49`.
- Blocking: `[]`.
- Disk free: `38015356928` bytes.
- Estimated additional active DB bytes: `3152501753`.
- Projected retention growth with safety: `11821881573` bytes.
- Storage projection status: PASS.
- Integrity: `ok`.
- Journal mode: `wal`.

Required indexes present:

- `ix_competition_upload_metric_flags_subterritory`
- `ix_ims_fact_upload_rep_product`
- `ix_ims_raw_upload_sheet_brick`
- `ix_ims_summary_rep_period_product`
- `ix_ims_upload_status_period`
- `ix_target_rep_period_product`

Production planner bütün kritik path'lerde bounded indexed SEARCH kullanıyor.

---

# 4. 50-UPLOAD SENTETİK SCALE TEST

CI'da yalnız küçük fixture testi değil, gerçek hacimli sentetik SQLite probe çalıştırıldı.

Seed hacmi:

- competition: **5,000,000 satır**
- raw: **1,404,550 satır**
- fact: **158,200 satır**
- sentetik DB: yaklaşık **505 MiB**

Ölçülen sorgular:

- scoped competition query: ~`0.0114 s`
- latest FACT query: ~`0.0015 s`
- raw brick query: ~`0.0001 s`

EXPLAIN kritik sorgularda doğrudan kompozit indeks kullanıyor.

Integrity: `ok`.

PR #141 regression suite:

- **291 collected**
- **290 passed**
- **1 skipped**
- **0 failed**

---

# 5. TEMSİLCİ SAYFASI PERFORMANS ÇALIŞMASI

Orijinal problem: temsilci detail ekranı yaklaşık **25–30 saniye** sürüyordu.

## PR #130

- SQL brick/period scope optimizer.
- Representative cache + per-process single-flight.
- Competition/raw bounded SQL.
- AI competition batch.
- Read indexes.
- Whole-upload normal-path `.all()` taramaları kaldırıldı.

PR #130 production sonucu yaklaşık:

- cold <0.5 s
- warm <0.2 s
- unscoped competition query = 0

## PR #132

AI aylık / 3 aylık / 6 aylık period hesaplarındaki N+1 kaldırıldı.

Önemli: **özellikler kaldırılmadı.** Aylık/3 aylık/6 aylık analizler aynen çalışır; yalnız gerekli 6 aylık veri batch okunur.

## PR #135

Temsilci market ekranında 7 ürün için tekrar eden `effective_product()` N+1 kaldırıldı.

- `ProductionResultService.effective_products(...)` batch resolution.
- ContextVar tabanlı execution-local override.
- 7 eski `effective_product()` çağrısı aynı preloaded batch'i kullanır.

Önemli: **7 ürün ve effective product business behavior kaldırılmadı.** Yalnız SQL fanout azaltıldı.

## Son production temsilci performansı — Issue #142

- cold max/p95: **0.4717 s**
- warm max/p95: **0.1749 s**
- max competition SELECT: **3**
- max total SELECT: **28**
- unscoped competition SELECT: **0**
- result: **PASS**

---

# 6. DEĞİŞTİRİLMEMESİ GEREKEN CANLI BUSINESS KURALLARI

- Production satış kaynağı önceliği: **P2 > P1 > IMS**.
- P1 geldiğinde IMS beklenmez; P1 IMS'in yerini hemen alır.
- P2 geldiğinde P1'in yerini alır.
- P2, P1 hiç gelmemiş olsa da final kaynak olabilir.
- Product-level fallback: P2'de ürün yoksa P1; P1'de de yoksa IMS.
- Kaynak yoksa **error**; sahte `0` üretme.
- Nationwide snapshot farklı source tiplerini birbirine karıştırmaz.
- Production realizasyonu `%100` üzerinde **kırpılmaz**.
- Decimal precision korunur.
- Prime engine mevcut payout / entitlement davranışı korunur.
- Dashboard / region / representative hesapları business redesign edilmez.
- Hedef business source/schema keyfi değiştirilmez.
- Official NATIONAL/region aggregate kişi toplamıyla ikame edilmez.
- Official Brick Spread FACT/SUMMARY/prim domainine karıştırılmaz; side-channel master olarak kalır.
- Ana SQLite DB WAL modunda kalır.
- User vault `instance/persistent/users.db` bağımsız korunur.
- Kullanıcı kayıtları DB temizliği veya IMS resetinde silinmez.
- Import validation failure durumunda mevcut canlı IMS yayında kalır; yarım veri publish edilmez.
- Acceptance isolated DB copy üzerinde çalışır.
- Tüm production gate'ler PASS olmadan managed service restart edilmez.

---

# 7. BOS / BOŞ / VACANCY KURALLARI

- `BOS != BOŞ`.
- `DİYARBAKIR BOS != DİYARBAKIR BOŞ`; ayrı stable Representative ID taşımalıdır.
- `BOS KADRO` ve `BOŞ KADRO` slot kimliğini kaybetmemelidir.
- `BOSTANCI` vacancy değildir.
- `BRICK` tokenı yalnız context olarak kullanılmalıdır; kendi başına vacancy identity değildir.
- Aynı contextte deterministik tek eşleşme yoksa tahmin yapılmamalı.
- Vacancy resolution başarısızsa accent-insensitive fuzzy zincirine fallback edilmemeli.
- Bir BOŞ/BOS slotuna ileride gerçek kişi atansa bile geçmiş IMS kayıtları geriye dönük başka kişiye taşınmamalı.
- Historic vacancy PK korunmalı; duplicate Representative yaratılmamalı.

Eski PR #70 / Issue #69 blocker'ları artık tarihsel kayıttır; son production acceptance bu sınıftaki kritik blocker'ları 0 göstermektedir.

---

# 8. DOSYA/ŞABLON BAĞIMSIZ IMS IMPORT MİMARİSİ

Kullanıcının şartı: importer tek bir Excel dosya adına, sheet sırasına veya sabit header pozisyonuna bağlı olmayacak.

Korunacak yaklaşım:

- sheet adı yalnız yardımcı/fallback sinyali;
- sheet sırası business identity değil;
- header satırı sabit değil;
- kolon sırası sabit değil;
- content/signature-first discovery;
- temsilci/ürün/brick/region + TL/KUTU/PP/target/actual/realization semantiğiyle rol keşfi;
- deterministik eşleşme varsa otomatik işle;
- gerçek anlam belirsizse FAIL/REVIEW;
- `0` gerçek data, blank değildir;
- derived/master eşleşmesi fiziksel hücre koordinatına değil semantik key'e dayanır.

Ana servisler:

- `app/services/workbook_preflight.py`
- `app/services/semantic_import_discovery.py`
- `app/services/workbook_semantic_reconciliation.py`
- `app/services/derived_master_verification.py`
- `app/services/representative_resolver.py`
- `app/services/vacancy_matching.py`
- `app/services/official_aggregate_service.py`
- `app/services/official_brick_spread_atomic.py`
- `app/services/ims_delta_service.py`
- `app/services/ims_delta_audit.py`
- `app/services/import_result_report.py`

---

# 9. PRODUCTION IMS ACCEPTANCE BASELINE

Canlı Jan Week 5 workbook:

`Tayfun-1_5.Hafta_Ocak_Brick_Analizi_.xlsx`

Issue #142 production acceptance:

- source: **28,091**
- stored: **28,091**
- competition: **99,756**
- fact: **3,164**
- summary: **791**
- target: **791**
- official aggregates: **168**
- sheets: **16/16 verified**
- representatives in manager report: **113**
- regions: **11**
- critical blockers: **0**
- NATIONAL/region reconciliation: **PASS**
- summary TL ≈ **144,903,094.39**
- summary UNIT = **1,706,908**
- target TL ≈ **137,664,417.84358248**
- target UNIT = **1,222,820**

Manager report: PASS.

---

# 10. PRODUCTION DEPLOY GÜVENLİK ZİNCİRİ — GÜNCEL

`.github/workflows/deploy.yml` production flow özeti:

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
15. **Projected DB capacity gate (+49 IMS).**
16. Representative read performance gate.
17. Live DB'den `/tmp/ims-acceptance-*` izole online backup.
18. `verify_ims_acceptance.py`.
19. `verify_ims_acceptance_extras.py`.
20. Production capacity snapshot.
21. **Yalnız tüm gate'ler PASS ise `systemctl restart`.**
22. `/login` health smoke.
23. Health PASS sonrası backup retention cleanup.
24. Persistent GitHub deployment evidence issue.

Restart script mevcut active service için gerçek `systemctl restart` kullanır; yalnız reload değildir.

---

# 11. BACKUP RETENTION

Backup temizliği tamamlandı ve production'da tek doğrulanmış rollback seti politikası aktif.

Kural:

1. Fresh `ipm` backup.
2. Fresh `users` backup.
3. Gerekli repair/pre-backfill backup.
4. Integrity / migration / DB capacity / representative performance / IMS acceptance.
5. Service restart.
6. `/login` health PASS.
7. Ancak bundan sonra eski managed + historical manual/repair DB backup'ları temizlenir.

Issue #142 retained IPM/users integrity: `ok`.

Aktif DB ve user vault hiçbir cleanup tarafından silinmez.

---

# 12. ORACLE FREE / A1 MIGRATION DURUMU

Mevcut production Oracle Free server yaklaşık 1 GB RAM'dir.

Ayrıca kullanıcıda `Bistbot` adlı ayrı instance vardır:

- Shape: `VM.Standard.E2.1.Micro`
- 1 OCPU / 1 GB RAM
- yaklaşık 47 GB boot volume

Yeni IMS için denenmiş hedef:

- `VM.Standard.A1.Flex`
- 2 OCPU
- 12 GB RAM
- Ubuntu 22.04 Minimal aarch64
- yaklaşık 46.6 GB boot
- mevcut VCN/subnet
- public IPv4
- mevcut SSH public key

Frankfurt AD1/AD2/AD3: `Out of capacity`.
1 OCPU / 6 GB da kapasite bulamadı.

**Şu anda migration yapılmayacak. Mevcut server production olarak kalacak.**

A1 kapasitesi gelecekte açılırsa:

- yeni VM parallel kurulacak;
- eski server kapatılmayacak;
- repo + venv + systemd + DB/user vault/settings migrate edilecek;
- full CI/acceptance/performance/capacity yeni makinede PASS olacak;
- trafik ancak bundan sonra taşınacak;
- eski server geçici rollback olarak tutulacak.

---

# 13. ÇALIŞMA ORTAMINDA ŞİMDİ YAPILACAKLAR

Kullanıcı yeni görev verene kadar production'da gereksiz değişiklik yapma.

Yakın dönem operasyon:

1. Mevcut Oracle Free production ile devam et.
2. Kalan yaklaşık **49 IMS** dosyasını kontrollü yükle.
3. Her import sonrası mevcut validation / optimize / passive checkpoint davranışını koru.
4. DB capacity, integrity, representative performance ve IMS acceptance gate'lerini gevşetme.
5. Tek `ipm.db` ile devam et; yıllık DB shard ekleme.
6. A1 kapasitesi açılırsa migration ayrı, kontrollü ve paralel çalışma olarak yapılabilir.
7. İleride ücretli compute/storage'a geçişte öncelik aynı DB ile vertical upgrade.
8. Gerçek SQLite sınırı ölçülürse PostgreSQL migration değerlendir.

---

# 14. CODEX BAŞLANGIÇ TALİMATI

Codex yeni çalışma ortamında ilk olarak:

1. Bu `PROJECT_WORK_PROGRESS.md` dosyasını oku.
2. `PROJECT_AUDIT.md` dosyasını oku.
3. `docs/MOBILE_CONTINUATION.md` dosyasını oku.
4. `main` branch'in halen `70562d85f25b82dda8d1cf370dfabf09d891659b` veya daha yeni doğrulanmış commit'te olduğunu kontrol et.
5. Son production evidence olarak Issue #142'yi doğrula.
6. Kullanıcının yeni talebini mevcut business/data invariants'a sadık kalarak uygula.
7. Kod değişikliği gerekiyorsa branch → test → PR → full CI → merge → production deploy → persistent evidence zincirini kullan.
8. Tamamlandı demeden önce gerçek production kanıtı göster.

## Hazır devam mesajı

**“`PROJECT_WORK_PROGRESS.md` içindeki 22 Ağustos 2026 checkpointinden devam et. Production Issue #142 SUCCESS ve canlı main `70562d85f25b82dda8d1cf370dfabf09d891659b`. SQLite +49 IMS capacity PASS, representative cold max 0.4717s / warm max 0.1749s, 28 total SELECT, unscoped competition 0. Tek `ipm.db` ile devam kararı var; yıllık DB shard ekleme. A1 Frankfurt kapasitesi yok, mevcut Oracle Free server kullanılmaya devam ediyor. P2>P1>IMS, product-level fallback, uncapped >100%, NATIONAL/region official aggregates, Official Brick Spread side-channel, user vault, WAL/single-writer ve fail-closed acceptance kurallarına dokunma. Yeni görevi branch/test/PR/deploy/evidence zinciriyle uygula.”**
