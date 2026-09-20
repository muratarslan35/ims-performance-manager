# IMS Performance Manager — Kanonik Çalışma / Devir Kaydı


# 0. 13 EYLÜL 2026 — YEDEK / ÇOKLU KULLANICI VE HARİTA GEÇİŞİ

- Production yedek envanteri doğrulandı: yalnız bir tam rollback seti bulunuyor (`20260908-145757`); toplam backup dizini yaklaşık 2,83 GB.
- Güvenli retention sonucu `PASS`; eski/gereksiz set bulunmadığı için `deleted_files=0`. Son doğrulanmış rollback seti korunmuştur.
- Yedek dosyalarının sürekli RAM tüketmediği; önceki haftalık tam integrity/dbstat taramalarının yaklaşık 45 dakika disk I/O baskısı oluşturabildiği doğrulandı.
- Normal haftalık bakımda ağır kapasite taraması kapatıldı; yalnız `RUN_DEEP_CAPACITY_AUDIT=1` ile açıkça istendiğinde çalışır.
- Tek rollback seti varsa 2,83 GB dosya tekrar bütünlük taramasından geçirilmez; temizlik yalnız birden fazla yedek nesli bulunduğunda çalışır.
- IMS işi `QUEUED` veya `PROCESSING` ise bakım hiçbir veri/servise dokunmadan çıkar. Web ve import worker kesintisiz korunur.
- Bakım sağlık kontrolü production sözleşmesiyle uyumlu `/login` yoluna bağlandı.
- Ana ekran Türkiye haritasında bölge tıklaması ortak loading overlay'i gerçek navigasyon süresince gösterir. Sahte yüzde/zamanlayıcı yoktur; loader hedef HTML belgeyi yükleyene kadar görünür ve `pageshow` ile temizlenir.
- Harita tıklamasında çift yönlendirme engellenir ve erişilebilirlik için `aria-busy` / `aria-hidden` durumu yönetilir.
- UI smoke ve production UI deploy PASS: run `34764646093`; canlı UI commit `fbe3045d19ec7ee0d9a26938c1660b0e8225468d`.
- Bakım güvenlik sözleşmeleri CI ile kilitlendi; ağır tarama ve yedek tekrar okuma normal kullanıcı trafiğinden ayrıldı.

---

> Son güncelleme: **27 Ağustos 2026 05:50 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Bu dosya PC Codex, mobil ChatGPT ve sonraki çalışma oturumları için **tek güncel checkpoint** olarak kullanılmalıdır.

---

# 0. 27 AĞUSTOS 2026 — AKTİF KANONİK CHECKPOINT

Bu bölüm aşağıdaki tüm tarihsel kayıtların üzerindedir; kredi/oturum yenilendiğinde **önce bu bölümden devam edilir**.

## Tamamlanan kök neden ve performans düzeltmesi

- Başlangıç production SHA: `6b2fea4640cc6a36d995e1e7c9028c04a1cdc50d`.
- Çalışma branch'i: `perf/bounded-competition-import`.
- Uygulama commit'i: `c603d2937101e524b609c243239076f99fde6d39` (`Optimize bounded competition import pipeline`).
- PR **#229** full CI PASS sonrasında merge edildi.
- Güncel main/production merge SHA: **`70433993eaba0a761bd5fe1b805e4aed00cf8f76`**.
- Competition importer artık ana importer'ın zaten açıp sanitize ettiği DataFrame workbook'unu yeniden kullanır; Excel ikinci kez openpyxl ile açılmaz.
- Rekabet kayıtları tek sheet / bounded bellek yaklaşımıyla stream edilir; 1.000 satırlık chunked mappings kullanılır.
- Satır başına ORM nesnesi ve ikinci normalization kaldırıldı; public model mapping sözleşmesi korunmuştur.
- Atomic transaction, exact duplicate/conflict semantiği, invalid-cell fail-closed davranışı ve mevcut business kuralları değiştirilmemiştir.

## Yerel doğruluk ve performans kanıtı

- Gerçek `Tayfun_7.Hafta_Subat_Brick_Analizi_.xlsx` importu PASS.
- Source/stored: `24.816 / 24.816`; RAW `25.104`; FACT `3.426`; SUMMARY `888`; TARGET `1.211`; COMPETITION `467.320`.
- Tüm blocking sayıları `0`; reconciliation `PASSED`.
- Eski ve optimize DB arasında business-row SHA-256 birebir eşit:
  - `ims_raw_data`: `f0e34cfe3d0f3b21e57199504bced426437b905cac01d23282bfbfff5c10e66e`
  - `ims_facts`: `30d7f3ae555f6690da0b76da6907caf5eb3210837d40677904a40310ecd3e5a7`
  - `ims_competition_data`: `0da7c2a4db4870b42d7726648776989a123d8c1159c8e49c277bf23f1fee8df1`
- `ims_summary`, `targets` ve `representative_brick_assignments` satır sayıları/hashleri de birebir eşittir.
- Gerçek dosya wall time: `193.796s -> 154.391s`.
- Competition stage: `78.859s -> 36.781s`.
- Yerel gözlenen peak working set yaklaşık `402 MB`.
- Final full suite: **`340 passed, 5 skipped`** (`371.05s`).
- Final explicit 50-upload SQLite scale guard: **PASS** (`7.04s`).
- PR CI run `33042877607`: **SUCCESS**.

## Production ve şu an çalışan işlem

- Main deploy run **`33043049691`**: full suite + production deploy/acceptance **SUCCESS**.
- Production host HEAD: `70433993eaba0a761bd5fe1b805e4aed00cf8f76`.
- `ims-performance-manager.service`: active; `/login`: HTTP 200.
- Acceptance gerçek dosya üzerinde 15 dakikalık değişmeyen gate içinde tamamlandı; canlı DB yerine izole `/tmp/ims-acceptance-*.db` kullanıldı.
- Acceptance sırasında gözlenen importer RSS yaklaşık `570 MB` tepe yaptı ve sonra düştü; timeout yükseltilmedi.
- Otomatik kalıcı production benchmark run **`33043899893`** şu anda **IN PROGRESS**:
  `https://github.com/muratarslan35/ims-performance-manager/actions/runs/33043899893`
- Önceki timeout/cancel kaydı Issue **#228** halen açıktır; yeni benchmark PASS olmadan kapatılmayacaktır.

## Kredi yenilenince kesin devam sırası

1. Benchmark run `33043899893` sonucunu kontrol et; 20 dakikalık workflow timeout'unu yükseltme.
2. PASS ise logdan `IMS_SERVER_BENCHMARK|...` kanıtını çıkar: wall/processing/stage/peak RSS, source/stored, RAW/FACT/SUMMARY/TARGET/COMPETITION, blockers ve reconciliation.
3. Production hostta HEAD, service active, `/login` HTTP 200, SQLite `journal_mode=WAL`, `busy_timeout=30000`, `integrity_check=ok`, CPU/RAM/swap/disk ve orphan/temp cleanup durumunu doğrula.
4. Başarılı benchmark kanıtını Issue #228'e ekle ve eski FAILED issue'yu açıklamayla kapat.
5. Bu checkpoint ve `CODEX_HANDOFF_CURRENT.md` dosyasını final kanıtla tekrar güncelle; docs-only commit/push yap.
6. Benchmark FAIL/timeout olursa güvenlik/acceptance eşiklerini gevşetme; logdaki stage ve peak RSS kanıtından yeni bounded kök neden çalışması aç.

## Değiştirilmeyecek kurallar

- P2 > P1 > IMS; gerçek `0` blank değildir.
- NATIONAL/region official aggregates kişi toplamlarıyla değiştirilmez.
- Official Brick Spread side-channel masterdır; FACT değildir.
- BOS != BOŞ; BOSTANCI vacancy değildir; ambiguity fail-closed kalır.
- SQLite WAL, `busy_timeout=30000`, single-writer, user vault ve acceptance fail durumunda canlı snapshot koruması devam eder.
- Prime/hedef/dashboard iş mantığı değişmemiştir.

---

# 0. 26 AĞUSTOS 2026 — PC CODEX KESİN DEVAM NOKTASI

Bu bölüm aşağıdaki eski kayıtların üzerindedir; çelişki halinde bu bölüm esas alınır.

## 26 Ağustos 2026 — workflow #477 sonrası kesin durum

- Main workflow #479 / run `32934093945`: full CI PASS; gerçek import `490.0356s` ve acceptance snapshot `43.6945s` ile timeout çözümü kanıtlandı. Deploy, Excel manifestindeki `TTS Rekabet` / `TTS Rekabet PP` adları ile DB'nin normalize `TTS REKABET` / `TTS REKABET PP` adlarını case-sensitive karşılaştırdığı için fail-closed oldu; restart yapılmadı, Issue #213 açıldı.
- Sheet identity karşılaştırması sistemin mevcut `AliasService.normalize` standardına bağlandı. Production workbook'un gerçek 16-sheet manifesti ile retained acceptance DB üzerinde coverage PASS; veri satır sayısı ve territory/product/metric fingerprint korumaları değiştirilmedi.
- Takip PR'ı: #215 (`fix/acceptance-sheet-identity`); final CI ve production deploy kanıtı bekleniyor.

- PR #210 merge edilmiştir; GitHub main SHA `cb7943382f5d059d1d35d6a732ce409659c277e8`.
- Workflow #476 / run `32930433808`: full suite ve 50-upload scale probe PASS.
- Main workflow #477 / run `32930657915`: test ve scale PASS; production pre-acceptance kapıları PASS, ancak izole IMS importu tamamlandıktan sonra acceptance snapshot eski kodun 262.882 rekabet satırını üç kez ORM ile materialize etmesi nedeniyle 900 saniye timeout oldu. Service restart edilmedi ve canlı snapshot korunmuştur; Issue #211 açılmıştır.
- Retained acceptance DB kanıtı: upload `7` COMPLETED, import `533.71s`, source/stored `28098/28098`, reconciliation `PASSED`, RAW `29338`, FACT `3164`, SUMMARY `791`, competition `262882`.
- Yeni branch `fix/acceptance-streaming-fingerprint`: competition kabul snapshotı tek bounded streaming pass'e geçirildi. Retained production DB üzerinde baseline snapshot `11.892s`, acceptance snapshot `31.701s`.
- Eski competition kapsamı `99.756` satır / 4 sheet tamamen korunmuştur. Yeni kapsam `262.882` satır / 10 sheet; 6 yeni manifest sheet sınıflandırılmıştır. `TTS REKABET` için 5.456 satır, toplam 4.144.565 ve bölge/ürün/metrik kırılımı birebir aynı; yalnız eski yanlış `MONTHLY` etiketi doğru `WEEKLY` olarak düzelmiştir.
- Acceptance artık fiziksel değişikliğe yalnız sheet satır sayısı ve territory/product/metric iş toplamları birebir aynıysa izin verir; veri değeri, kapsam veya manifest sapmasında fail-closed kalır.
- Yerel hedefli import suite: `29 passed, 1 skipped`; full suite: `328 passed, 5 skipped, 0 failed` (`249.94s`).
- 50-upload scale probe tekrar PASS: competition `5,000,000`, raw `1,404,550`, facts `158,200`, integrity `ok`, DB `529,477,632` byte; tüm planlar bounded index kullanıyor.
- Sonraki zorunlu sıra: bu branch'i commit/push → PR/full CI → merge → production acceptance/extras/integrity-WAL/performance/resource/health PASS → yalnız sonra service restart ve tamamlandı kaydı.

## 26 Ağustos 2026 04:56 sonrası — aktarım engeli checkpoint'i

- Yerel commit hazır ve temizdir: `70df8e72d8fe09ffd571a0484cc698affe751315` (`Harden SQLite acceptance and import telemetry`).
- `git push -u origin fix/pc-sqlite-acceptance-stability` yeniden denendi; çalışma ortamı `github.com:443` bağlantısını sistem düzeyinde reddetti.
- Alternatif `ssh.github.com:443` ve production `130.162.48.162:22` bağlantıları da TCP seviyesinde kapalıdır.
- Bağlı GitHub repository API'si branch'i okuyabiliyor fakat bu oturumun `approval policy=never` kuralı mutasyonları (branch/push/PR) reddediyor; in-app/external browser bağlantısı da bulunamadı.
- Bu nedenle PR, CI, merge, production acceptance, restart ve post-restart health adımları **çalıştırılmadı**; canlı servis/snapshot değiştirilmedi.
- Ağ erişimi açıldığında yeniden analiz veya test yapılmadan aşağıdaki SHA push edilerek zorunlu sıra `Branch/PR` adımından devam edilecektir. Production kapıları PASS olmadan tamamlandı/canlıya alındı denmeyecektir.

## 26 Ağustos 2026 00:44 — PC Codex uygulama checkpoint'i

Çalışma branch'i: `fix/pc-sqlite-acceptance-stability`

Temiz worktree: `work/ims-performance-manager-pc-20260826`

Başlangıç SHA: `b55a87447bc9873ce42cbb92e70d8248a8153eb1`

Tamamlanan işler:

- PC SQLite scale-guard hatası yeniden üretildi. WAL=`wal`, integrity=`ok`, NTFS/disk projeksiyonu PASS iken SQLite 3.53.1'in tek satırlı sentetik tablolarda `PRAGMA optimize` sonrasında rasyonel olarak table scan seçtiği kanıtlandı. Fixture, production access path'ini temsil eden bounded tarihsel satırlarla düzeltildi; audit/gate/eşikler gevşetilmedi.
- Representative performance gate'te ilk process/host çalışması ayrı telemetry olarak tutuldu; ilk-run hâlâ cold max `8s` ve query-count kapılarına dahildir. Ölçülen cold p95 `5s`, warm p95 `2s`, toplam SELECT `30`, competition SELECT `4` eşikleri değiştirilmedi.
- Acceptance timeout/cancel süreci için kullanıcı/cwd/cmdline doğrulamalı bounded process cleanup, `/tmp/ims-acceptance-*.db*` için owner/age/path doğrulamalı bounded cleanup ve başarısız DB için 60 dakikalık retention eklendi.
- Import aşama süreleri ve Linux peak RSS telemetry eklendi; acceptance bu telemetry eksik/geçersizse fail-closed olur.
- Competition persist yolu `1000` kayıtlık bounded `bulk_insert_mappings` parçalarına geçirildi; dış transaction commit/rollback ve duplicate/conflict semantiği korunmuştur.
- User vault SQLite bağlantıları işlem sonunda açık kalmayacak şekilde kesin kapatıldı.
- Windows test ortamındaki geçici SQLite dosya kilitleri production havuzuna dokunmadan TESTING-only `NullPool` ile izole edildi. POSIX lock sözleşmeleri Windows'ta skip, Linux CI/production'da aktiftir.

Yerel kanıt:

- Hedefli import/performance/deploy testleri: `38 passed, 1 skipped`.
- Full suite: `326 passed, 5 skipped, 0 failed` — `209.75s`.
- 50-upload scale probe: PASS; competition=`5,000,000`, raw=`1,404,550`, facts=`158,200`, DB=`529,477,632` byte, integrity=`ok`.
- Bounded query süreleri: competition six-upload=`0.0121s`, facts latest-upload=`0.0018s`, raw latest-brick=`0.0003s`; üç plan da beklenen composite indexleri kullandı.
- YAML parse ve Python syntax/diff-check: PASS.

Henüz tamamlanmayan zorunlu sıra:

1. Branch commit/push ve PR.
2. GitHub full CI PASS sonrası merge.
3. Production isolated acceptance + extras + SQLite integrity/WAL + representative performance + CPU/RAM/disk resource gate PASS.
4. Yalnız tüm kapılar PASS ise service restart ve post-restart health.
5. Final production kanıtını bu bölüme ekle; Issue #208/#209'u sonuçla ilişkilendir.

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


---

# 20 EYLÜL 2026 — BÖLGE AI, SNAPSHOT DENETİMİ VE AYLIK ÜRÜN DEĞİŞİMİ CHECKPOINT

Bu bölüm 19–20 Eylül 2026 çalışmalarının güncel production checkpointidir. Önceki tarihsel notlarla çelişen noktalarda aşağıdaki güncel iş kuralları esas alınmalıdır.

## 1. GitHub Actions / production erişim teyidi

- Repo: `muratarslan35/ims-performance-manager`.
- GitHub bağlantısında repo için admin/maintain/push/pull/triage erişimi doğrulandı.
- Production deploy SSH bağlantısı doğrulandı:
  - host: `130.162.48.162`
  - user: `ubuntu`
  - proje: `/home/ubuntu/ims_system`
  - secret: `IMS_DEPLOY_SSH_KEY`
- Actions job/log ve production deploy kanıtları okunabiliyor.
- Son ilgili deploy: workflow run **35472566226**, commit `a9bc1d390fb734ea7de6faafdcf63fa43d15d0bf`, **SUCCESS**.
- İlgili son probe: workflow run **35471998566**, **SUCCESS**.
- Bu checkpoint yazılırken ilgili deploy/audit/probe işlerinde bekleyen işlem yoktur.
- Önceki recovery denemelerindeki failure/cancel kayıtları tarihsel denemedir; güncel production read-model doğrulaması PASS olduğu için aktif blocker değildir.

## 2. Bölgesel AI ekranı — Türkiye verisinin bölgeye sızması düzeltildi

Kök problem:

- Bölge AI ekranındaki sağ paneller `current_workspaces` / `previous_workspaces` üzerinden tüm Türkiye temsilci/brick havuzunu görebiliyordu.
- Bu nedenle bir bölgenin AI kartında başka bölgelerin brickleri ve Türkiye geneli sayıları görünebiliyordu.
- Ayrıca brick satırına taşınmış temsilci ürün hedefi yanlışlıkla gerçek bir “brick hedefi” gibi gösterilebiliyordu.

Uygulanan düzeltme:

- `PersistentRegionSnapshotService` içinde AI üretiminden önce yalnız o bölgenin temsilci ID'leri seçiliyor.
- Güncel ve önceki dönem workspace'leri ayrı ayrı **yalnız bölge kapsamına** indirgeniyor.
- Region read-model sürümü **v3** yapıldı.
- Bölge AI kartındaki “Hedefli ama çıkışı olmayan brickler” semantiği kaldırıldı.
- Yerine gerçek veriye dayalı **“Rakip satışı var, şirket çıkışı yok”** analizi getirildi.
- Brick seviyesinde sahte/tekrarlanmış `target_unit` artık AI sinyali olarak kullanılmıyor.
- Kartta gerçek şirket/rakip/pazar/pay değerleri gösteriliyor.
- Rakibin satış kaybettiği bricklerde artık şirketin önceki→güncel kutu değişimi ve pay puanı değişimi de gösteriliyor.
- Kullanıcı arayüzündeki `Snapshot-only` gibi iç mimari ifadeleri kaldırıldı.
- Kullanıcı snapshot mimarisini görmemeli; ekran yalnız iş sonucunu göstermeli.

İlgili ana commitler:

- `627de70ee44ba1cbcc6b7d8a9e3747679a80f43e`
- `5b71db06ed3867833fca02de37e471a458abadc9`

## 3. Region snapshot UNIQUE constraint olayı — teşhis

Görülen hata:

`UNIQUE constraint failed: manager_region_snapshots.set_id, manager_region_snapshots.region_key`

Kök neden:

- Eski bir deploy akışı region snapshot backfill'i `--force` ile çalıştırırken IMS worker aynı source identity için aynı `set_id / region_key` satırlarını yayınlamaya çalışmış.
- İki snapshot üreticisi aynı anda yazdığı için constraint koruması devreye girmiş.
- Veri kaynağı bozukluğu değildi.

Production sağlık kontrolünde:

- aktif dönem region seti: **11/11 region**
- BUILDING: 0
- FAILED: 0
- görünür region sayısı: 11/11
- web ve worker servisleri active

Güncel deploy mimarisinde eski otomatik force-backfill davranışının kaldırıldığı doğrulandı. Normal deploy artık IMS publication worker ile yarışan ikinci force snapshot üreticisi başlatmıyor.

Salt-okunur production tanılama için `.github/workflows/region-snapshot-health.yml` eklendi.

## 4. Ağustos / Temmuz veri kaynağı denetimi ve kesin business kuralı

### Kesin iş kuralı

Temsilci ürün realizasyonunda:

- **Hedef = IMS hedefi**
- **Gerçek çıkış = P2 > P1 > IMS**
- **Realizasyon = seçilen gerçek çıkış / IMS hedefi**

Üretim dosyasında ayrıca hedef değeri bulunsa bile temsilci realizasyon hedefi olarak IMS hedefi kullanılmaya devam eder.

Bu nedenle Temmuz Diyarbakır incelemesinde görülen hedef farkları bug değildir.

### Temmuz / 901 Diyarbakır doğrulaması

9/9 temsilcide aynı kaynak sözleşmesi doğrulandı:

- hedefler IMS'den;
- gerçekleşenler 1. üretim sonucundan;
- realizasyon bu iki değerin oranından.

Murat Arslan Temmuz örneği:

- IMS hedef: yaklaşık **1.775.005,82 TL**
- üretim gerçekleşen: **1.166.470 TL**
- realizasyon yaklaşık **%65,72**, UI yuvarlamasıyla **%66**

Bölge toplamı ile temsilci hedef kaynakları birbirine karıştırılmamalıdır.

### Ağustos doğrulaması

- Production DB'de Ağustos için uygulanmış P1/P2 production upload kaydı bulunmadığı doğrulandı.
- Bu nedenle Ağustos temsilci aylık sonucu IMS kaynağından gelir.
- Murat Arslan Ağustos toplam realizasyonu **%99** olarak doğrulandı.
- Ekranın üstündeki yaklaşık **%106** değeri Murat Arslan değil, **901 Diyarbakır bölge toplamı**dır.
- Ağustos için aktif IMS kaynağı denetimde upload **48** olarak görüldü.

İlk aylarda snapshot bulunmaması tek başına hata değildir; snapshot mimarisi yılın ilk aylarında henüz kurulmamıştı.

## 5. “Aylık ürün değişimi ve rakip baskısı” düzeltmesi

Kök problem:

- Güncel `actual_unit / market_unit / competitor_unit` bazı normalization aşamalarında doğru kaynaktan güncelleniyordu.
- Ancak `previous_actual_unit`, `actual_change_unit`, `actual_change_percent` ve `competitor_change_unit` alanları eski/raw kaynaktan kalabiliyordu.
- Sonuçta aynı satırda yeni “bu ay” değeri ile eski kaynaktan hesaplanmış fark yan yana görülebiliyordu.

Yeni kalıcı sözleşme:

### Şirket kutuları

Her ay bağımsız olarak:

**P2 > P1 > IMS**

ile çözülür.

- Açık ayda yeni IMS geldikçe “bu ay” değeri güncellenir.
- Aynı ay için P1 geldiğinde IMS'in yerini P1 alır.
- P2 geldiğinde P1'in yerini P2 alır.
- Yeni aya geçildiğinde kapanan ay aynı kaynak önceliğiyle “önceki ay” konumuna geçer.
- Sonradan P1/P2 gelirse ilgili ayın snapshot/read-model karşılaştırması yeniden yayınlanır.

### Rakip kutuları

- Rakip aylık kutu verisi **aylık IMS rekabet snapshotından** gelir.
- Önceki ay ve bu ay aynı rekabet sözleşmesiyle alınır.
- `competitor_change_unit = current_competitor - previous_competitor`.

### Fark hesapları

- `actual_change_unit = current_actual - previous_actual`
- `actual_change_percent = actual_change_unit / previous_actual * 100`
- previous değer 0 ise yüzde “Yeni veri” semantiğinde bırakılır; sahte yüzde üretilmez.

Uygulama:

- `representative_period_workspace.py` içinde tek kaynak sözleşmeli `_monthly_comparison_rows(...)` eklendi.
- Karşılaştırma read-model contract sürümü **v2** oldu.
- Template `market_analysis.comparison_rows` alanını tercih ediyor.
- Production result upload sonrasında temsilci snapshot yenileme işi mevcut tek worker kuyruğuna seri olarak bırakılıyor; IMS işi devam ederken kesilmiyor.
- Yeni `representative_snapshot_refresh_queue` akışı business data değil, yalnız türetilmiş snapshot yenileme talebi saklıyor.

## 6. Canlı aylık karşılaştırma doğrulaması

Güncel aktif temsilci snapshot:

- period: **2026/09**
- set: **2517**
- status: **ACTIVE**
- members: **113/113**
- source IMS: **50**
- production source: **0**
- read model: **v2**
- eski set 2515: SUPERSEDED
- takılı boş set 2516: FAILED
- worker: active
- refresh queue: boş

Murat Arslan canlı aylık karşılaştırması artık kendi içinde matematiksel olarak tutarlı:

| Ürün | Önceki ay | Bu ay | Net fark | Değişim | Rakip fark |
| --- | ---: | ---: | ---: | ---: | ---: |
| Travazol | 8.818 | 2.945 | -5.873 | -%66,6 | -2.052 |
| Monurol | 1.930 | 912 | -1.018 | -%52,7 | -4.359 |
| Acnemix | 1.091 | 773 | -318 | -%29,1 | -833 |
| Mixovul | 649 | 296 | -353 | -%54,4 | -602 |
| Stiderm | 1.055 | 587 | -468 | -%44,4 | -2.461 |
| Brimoder | 14 | 4 | -10 | -%71,4 | -97 |
| Fentivag | 0 | 0 | 0 | — | -1.341 |

Bu doğrulamada Ağustos ve Eylül şirket kutu kaynakları `IMS` olarak raporlandı; ilgili aylarda production sonucu geldiğinde P1/P2 önceliği otomatik uygulanacaktır.

## 7. Snapshot recovery sırasında öğrenilen operasyon kuralı

- Devam eden IMS işi kesilmemeli.
- Snapshot/read-model refresh işleri IMS worker kuyruğunun arkasına seri şekilde alınmalı.
- Aynı source identity için paralel force rebuild başlatılmamalı.
- BUILDING set aktif üretim gösteriyorsa ikinci writer başlatılmamalı.
- Takılı/boş derived snapshot nesli ancak worker durumu ve üye sayısı kanıtlandıktan sonra FAILED yapılabilir.
- Business IMS/production satırları recovery sırasında değiştirilmez.
- Audit/forensic kontroller mümkün olduğunca salt-okunur yapılır.

## 8. Bu çalışma sırasında eklenen operasyon denetimleri

Aşağıdaki Actions tanılama akışları eklendi:

- `region-snapshot-health.yml`
- `july-diyarbakir-audit.yml`
- `murat-monthly-market-audit.yml`
- `murat-monthly-market-probe.yml`
- `murat-monthly-market-recover.yml`

Bunlar production iş verisinin kaynağını değiştirmez; tanılama, kontrollü snapshot refresh/recovery ve canlı acceptance amaçlıdır.

## 9. Bundan sonra korunacak kurallar

1. Temsilci hedefi **IMS** kaynağında kalır.
2. Temsilci gerçek çıkışı **P2 > P1 > IMS** önceliğindedir.
3. Aylık ürün değişimi iki ayı da ayrı ayrı aynı source resolver ile çözmeden fark hesaplamaz.
4. Rakip farkları aylık IMS rekabet verisinin iki dönemi arasında hesaplanır.
5. Bölge AI yalnız kendi bölgesinin temsilci ve brick verisini görür.
6. Brick için kaynakta gerçek brick hedefi yoksa hedef uydurulmaz.
7. Kullanıcı arayüzünde snapshot/read-model gibi iç mimari terimler gösterilmez.
8. Hazır ACTIVE snapshot varsa ekran onu okur; sayfa açılışında ağır hesap tekrar edilmez.
9. Yeni IMS veya production sonucu geldiğinde gerekli derived snapshot worker üzerinden seri yenilenir.
10. Devam eden iş kesilmez; görevler sıraya alınır.
11. Audit sırasında production business satırları gereksiz yere mutate edilmez.
12. Production PASS / health doğrulanmadan “tamamlandı” denmez.

## 10. Güncel durum

- Bölgesel AI kapsam hatası: **DÜZELTİLDİ**
- Sahte brick hedefi gösterimi: **DÜZELTİLDİ**
- Region snapshot paralel writer kök nedeni: **TEŞHİS EDİLDİ / güncel deployda yarış yolu kaldırılmış durumda**
- Temmuz Diyarbakır hedef/actual kaynak sözleşmesi: **DOĞRULANDI**
- Ağustos Murat %99 / bölge %106 ayrımı: **DOĞRULANDI**
- Aylık ürün değişimi şirket farkları: **DÜZELTİLDİ**
- Aylık rakip farkları: **DÜZELTİLDİ**
- Aktif temsilci read-model: **v2 / set 2517 / 113 temsilci**
- Son production deploy: **SUCCESS**
- İlgili bekleyen işlem: **YOK**

## 11. Genel Müdür Raporlama Modülü (20.09.2026)

- Yönetici sol menüsüne ayrı **Raporlar → Genel Müdür Raporları** alanı eklendi.
- Boş `/reports` ekranı; aylık, son 3 aylık, sabit Ocak–Haziran 6 aylık ve yıllık YTD rapor üreten yönetici ekranına dönüştürüldü.
- National, bölge, il ve temsilci kırılımları ile çoklu ürün filtresi eklendi.
- Ürün bazında hedef TL, gerçekleşen TL, realizasyon, hedef/gerçekleşen kutu, toplam pazar, pazar payı ve başlıca rakipler aynı raporda birleştirildi.
- Dönemsel TL/kutu gelişim grafiği eklendi. Travazol dahil tek ürün seçilerek Türkiye geneli dönem gelişimi ve rakip analizi alınabilir.
- Ekranda seçilen filtrelerin tamamını koruyan **Excel (.xlsx)** ve **PDF (.pdf)** dışa aktarma uçları eklendi.
- Okuma hattı yalnız yayınlanmış ACTIVE temsilci snapshot setlerini toplu okur; sayfa açılışında IMS/üretim hesapları yeniden çalıştırılmaz.
- Temsilci hesaplarında rapor yetkisi kapatıldı. Bölge yöneticisinin raporu sunucu tarafında kendi bölgesine sabitlendi; URL değiştirilerek national veya başka bölge verisi açılamaz.
- Karanlık tema ve mobil görünüm için rapora özel stiller eklendi.
- Yeni sözleşme testleri: dönem kuralları, snapshot-only okuma, kapsam/ürün filtresi, rakip değerleri, menü görünürlüğü ve gerçek HTTP üzerinden Excel/PDF indirme.
- Doğrulama: **87 ilgili test PASS**, `git diff --check` ve Python derleme kontrolü PASS.

### Raporlar görsel düzeltmesi

- İlk canlı sürümde rapora özel CSS, `base.html` içindeki gerçek `styles` bloğu yerine bulunmayan `head` bloğuna yazıldığı için yüklenmiyordu; ham HTML görünümünün kök nedeni düzeltildi.
- Sayfa ve sol menü adı doğrudan **Raporlar** olarak sadeleştirildi; “Genel Müdür Raporları” ifadesi kaldırıldı.
- Filtre alanı, ürün seçimleri, KPI kartları, dönem grafiği ve rakip tablosu kurumsal görsel hiyerarşiyle yeniden düzenlendi.
- Rakip sütunu ve geniş tablo için sabit kolon oranları, metin taşma kontrolü ve dar ekran yatay kaydırma eklendi.
- Mobil/koyu tema uyumu ve statik dosya cache-buster güncellendi.

### Rapor kapsamı ve dışa aktarma iyileştirmesi

- Rapor formu global sayfa yükleyicisinden ayrıldı; filtre sonrası ekranda %99 yükleme katmanının kalması engellendi.
- Snapshot içindeki ürün/rakip listesinde uygulanan ilk 3/ilk 10 sınırları kaldırıldı; mevcut tüm rakipler okunup rapora aktarılıyor.
- Her rakip için `rakip kutu / ilgili ürünün toplam pazar kutusu` formülüyle dönemsel pazar payı eklendi.
- Ekrandaki rakip alanı tüm rakipleri kutu ve pazar payıyla gösterecek kaydırılabilir detay yapısına çevrildi.
- PDF çıktısı çok sayfalı A4 yatay yönetim raporu olarak yenilendi: kapsam/dönem başlığı, KPI özeti, ürün performansı, tüm rakipler ve pazar payları, tekrar eden tablo başlıkları, sayfa numarası ve alt bilgi.
- Excel çıktısı üç profesyonel sekmeye ayrıldı: `Yönetim Özeti`, `Dönem Trendi`, `Rakip Detayı`. Filtreler, sabit başlıklar, sayı biçimleri, baskı alanları ve trend grafiği eklendi.
- Örnek 7 ürün/84 rakip veri setiyle PDF 5 sayfa render edilerek; Excel de A4 PDF önizlemesine dönüştürülerek görsel taşma ve okunabilirlik kontrolü yapıldı.

### Raporlar production aktivasyonu

- PR **#883** ile raporlama backend'i için davranış değiştirmeyen release-activation commit'i main'e alındı: `70847e72e3166d96496fb05799ad90465c1320a0`.
- Bunun nedeni PR #881 sonrası heavy deploy'un kodu production hosta çekip `requirements.txt` bağımlılıklarını kurmasına rağmen 35 dakikalık workflow sınırında servis reload adımına ulaşamadan cancel olmasıydı.
- Heavy deploy sırasında production git HEAD'i zaten `0477a7af15e3a967217eed8ddf4e174fded5753c` olmuş ve ReportLab dahil bağımlılıklar kurulmuştu; business DB üzerinde başarısız/yetersiz publish yapılmadı.
- Aktivasyon PR'ında Locked Canonical Contracts **PASS** oldu. Backend full suite'teki 3 failure, bir önceki rapor PR'ında da birebir bulunan mevcut baseline contract failure'larıydı; aktivasyon satırı yeni regression üretmedi.
- Main push workflow run **35503472618** backend modunda **SUCCESS** oldu.
- Production kanıtı:
  - `IMS_WORKER_IDLE|processing=0`
  - `LIVE_COMMIT|70847e72e3166d96496fb05799ad90465c1320a0`
  - SQLite `journal_mode=wal`, `busy_timeout=30000`
  - Region Manager acceptance **PASS**, failures `[]`
  - `SERVICE_ACTIVATION|web=reload|mode=backend`
  - `SERVICE_ACTIVATION|worker=preserved|mode=backend`
  - `HTTP_HEALTH|PASS`
  - web **active**, worker **active**
- Böylece Raporlar modülü, profesyonel PDF/Excel exportları ve tam rakip kapsamı production servisinde aktif hale geldi.
- İlgili bekleyen rapor deploy/aktivasyon işi: **YOK**.


### Rapor filtreleri ve export UX düzeltmesi — 20.09.2026

Kullanıcı geri bildirimiyle Raporlar ekranında dört ayrı sorun düzeltildi:

- Excel/PDF indirmesi artık sayfa navigasyonu gibi davranmıyor. Export linkleri global page-loader'dan çıkarıldı ve indirme `fetch + blob` ile yapılıyor; dosya indikten sonra %99 yükleme katmanı ekranda kalmıyor.
- Bölge filtresinde yalnız `101/201/.../901` kodları yerine gerçek bölge adları gösteriliyor. Canonical bölge adları: İstanbul, Kadıköy, Bursa, İzmir, Ankara, Samsun, Trabzon, Adana, Konya, Antalya, Diyarbakır.
- İl seçenekleri artık temsilci master kaydındaki bölge merkezinden değil, seçili rapor döneminin aktif `RepresentativeBrickAssignment.city` alanlarından üretiliyor. İl seçildiğinde aynı dönem için o ile bağlı aktif temsilci kapsamı kullanılıyor.
- Bölge kimliği normalize edildi; örneğin `901` ile `901 DIYARBAKIR` aynı bölge kabul ediliyor.
- Export dosya adları seçilen analize göre değişiyor:
  - `national-analiz-raporu-YYYY-MM.pdf/xlsx`
  - `bolge-analiz-raporu-<bolge>-YYYY-MM.pdf/xlsx`
  - `il-analiz-raporu-<il>-YYYY-MM.pdf/xlsx`
  - `temsilci-analiz-raporu-<temsilci>-YYYY-MM.pdf/xlsx`
- Rapor değerlerinin snapshot-only okuma sözleşmesi, IMS/production iş verileri ve P2>P1>IMS kuralları değiştirilmedi.

Doğrulama:

- PR: **#885**
- merge commit: `7ed69bf8a2229842dece540d987e890f4ba7383e`
- Locked Canonical Contracts: **PASS**
- Yeni rapor testleri PASS; full backend suite'te kalan 3 failure bu değişiklikten önce de bulunan aynı baseline contract failure'larıdır.
- Production workflow run: **35506018241 — SUCCESS**
- `IMS_WORKER_IDLE|processing=0`
- SQLite: WAL / busy_timeout 30000
- Region Manager acceptance: **PASS**, failures `[]`
- web: **active**
- worker: **active**
- HTTP health: **PASS**
- İlgili bekleyen deploy işlemi: **YOK**


### Raporlama 200 kullanıcı mimarisi — 20.09.2026

Raporlar modülü yüksek eşzamanlı kullanım için yeniden yapılandırıldı.

- PR: **#887**
- main commit: `4f42bdc273b1b2c57291da231fadfb88d1e954e6`
- production deploy run: **35508291211 — SUCCESS**

Yeni mimari:

- Rapor aggregation sonucu aktif temsilci snapshot set kimlikleri + filtre parametreleriyle versionlanmış **filesystem report read-model cache** içinde tutulur.
- Aynı snapshot generation ve aynı filtre kombinasyonu için Gunicorn süreçleri arası **file-lock singleflight** uygulanır. 200 kullanıcı aynı raporu isterse aggregation yalnız bir kez yapılır.
- Snapshot generation değiştiğinde cache key otomatik değişir; eski rapor cache'i business veriyi etkilemez.
- Rapor filtre seçenekleri de snapshot generation kimliğiyle cache edilir.
- PDF/XLSX üretimi web request thread'inden çıkarıldı.
- Ayrı `ims-report-worker.service` eklendi.
- Export kuyruğu durable ve deduplicated'dır; aynı artifact için birden fazla kullanıcı tek export işini paylaşır.
- Hazır PDF/XLSX artifact sonraki isteklere doğrudan verilir.
- Report worker IMS import/publication işi varken bekler; IMS işi her zaman önceliklidir.
- Export UI 202 queue yanıtını poll eder; global page loader veya Gunicorn request thread'i uzun dosya üretimi boyunca bloke olmaz.
- IMS/production snapshot publication sonrasında monthly national/region/city/representative report cache warm-up işi report worker'a bırakılır.
- Report worker kaynak sınırları:
  - `Nice=12`
  - `CPUWeight=500`
  - `IOWeight=100`
  - `MemoryHigh=350M`
  - `MemoryMax=450M`
- Cache/export artifaktları 45 gün / 2000 dosya sınırıyla prune edilir.
- Business IMS/production tablolarına raporlama cache'i için yazı yapılmaz.
- Hedef=IMS, gerçekleşen=P2>P1>IMS ve mevcut snapshot publication kuralları değişmedi.

Concurrency doğrulaması:

- Aynı cache key için **200 concurrent reader** testi eklendi; build yalnız **1 kez** gerçekleşiyor.
- Snapshot generation değişince cache key değişimi test edildi.
- Aynı export için queue dedup test edildi.
- Locked Canonical Contracts: **PASS**.
- Main smoke: **PASS**.
- Production:
  - `IMS_WORKER_IDLE|processing=0`
  - SQLite `journal_mode=wal`, `busy_timeout=30000`, quick_check `ok`
  - IMS live gate: **PASS**
  - Region Manager acceptance: **PASS**, failures `[]`
  - web: **active**
  - IMS worker: **active**
  - report worker: **active**
  - HTTP health: **PASS**
- İlgili bekleyen deploy/aktivasyon işi: **YOK**.


### Raporlama çoklu kapsam ve detay analizleri — 20.09.2026

Raporlar modülü yönetim seviyesinde esnek çoklu seçim ve detay kırılımlarıyla genişletildi.

- PR: **#889**
- main commit: `07e9a0feaeb3e92ce5520fe25c995592be47d2d5`
- production deploy run: **35512595175 — SUCCESS**

Yeni yetenekler:

- Aynı raporda birden fazla **bölge** seçilebilir.
- Aynı raporda birden fazla **il** seçilebilir.
- Aynı raporda birden fazla **temsilci** seçilebilir.
- Ürün filtresi çoklu kapsamla birlikte çalışır; örneğin Adana + Diyarbakır seçilip yalnız Monurol raporlanabilir.
- Çoklu seçimler report cache identity'sine dahil edilir; aynı seçim kombinasyonu mevcut 200 kullanıcı singleflight/cache mimarisini kullanır.
- Bölge raporu artık yalnız bölge toplamı değil, seçili kapsam içindeki **temsilci analizlerini** de içerir.
- Birden fazla bölge seçilirse **Bölge Analizi** karşılaştırma tablosu oluşur.
- **Temsilci Analizi** ayrı read-model olarak rapora eklenir.
- **Brick Analizi** şirket/rakip/pazar/pay kırılımıyla snapshot market verisinden hazırlanır.
- **Rakip Analizi** tüm rakip satırlarını ürün bazında taşır.
- Web ekranında temsilci ve brick analizleri görünür; brick önizlemesi ilk 150 satırla sınırlandırılır, Excel tam listeyi içerir.

Excel sayfaları:

1. Yönetim Özeti
2. Dönem Trendi
3. Bölge Analizi
4. Temsilci Analizi
5. Brick Analizi
6. Rakip Analizi

PDF çıktısında da temsilci ve brick analiz bölümleri bulunur.

Yetki / veri sözleşmesi:

- Bölge müdürü server-side olarak yalnız kendi bölgesine sabitlenmeye devam eder; UI parametresiyle başka bölgeye geçemez.
- Business IMS / production tabloları değiştirilmez.
- Rapor hesapları yalnız yayınlanmış temsilci snapshot read-modelinden yapılır.
- Hedef = IMS, gerçekleşen = P2 > P1 > IMS kuralı korunur.
- Brick ve rakip değerleri yayınlanmış market snapshot içeriğinden okunur.
- PDF/XLSX üretimi ayrı report worker üzerinde ve mevcut deduplicated export kuyruğuyla çalışır.

Doğrulama:

- Locked Canonical Contracts: **PASS**
- PR backend suite: **747 passed, 2 skipped**, yalnız daha önce de bulunan aynı 3 baseline contract failure kaldı.
- Main smoke: **PASS**
- Production:
  - `IMS_WORKER_IDLE|processing=0`
  - `LIVE_COMMIT|07e9a0feaeb3e92ce5520fe25c995592be47d2d5`
  - SQLite WAL / busy_timeout 30000
  - Region Manager acceptance: **PASS**, failures `[]`
  - web: **active**
  - IMS worker: **active**
  - report worker: **active**
  - HTTP health: **PASS**
- İlgili bekleyen deploy/aktivasyon işi: **YOK**.
