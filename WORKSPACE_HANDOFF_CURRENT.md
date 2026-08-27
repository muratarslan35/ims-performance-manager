# IMS Performance Manager — CURRENT WORKSPACE HANDOFF

> Tarih: **27 Ağustos 2026 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Durum: **AKTİF / EN GÜNCEL DEVİR NOKTASI**  
> **Yeni çalışma ortamı önce bu dosyayı okumalıdır.** `PROJECT_WORK_PROGRESS.md` ve eski issue/benchmark kayıtları tarihsel kanıttır; bu dosyayla çelişen eski checkpointlere geri dönülmemelidir.

---

## 1. Kullanıcı hedefi ve çalışma kuralı

Kullanıcı IMS import tarafını artık tamamlayıp dashboard geliştirmesine geçmek istiyor. Mevcut mimari ve business kuralları korunacak; gereksiz refactor yapılmayacak.

Kesin kurallar:

- P2 > P1 > IMS önceliği korunur.
- Gerçek `0` boş hücre değildir.
- NATIONAL / region official aggregate değerleri temsilci toplamıyla değiştirilmez.
- Official Brick Spread side-channel masterdır; FACT değildir.
- `BOS` ve `BOŞ` ayrı kimliklerdir; `BOSTANCI` vacancy değildir.
- Historic vacancy PK reuse ve ambiguity fail-closed korunur.
- SQLite WAL + `busy_timeout=30000` + single-writer + user vault korunur.
- Prime, hedef, dashboard hesapları ve %100+ iş mantığı değiştirilmez.
- Import emin olmadığı veriyi tahmin ederek DB'ye yazmaz; fail-closed kalır.
- Ağır testler yalnız importer/DB değişikliklerinde; dashboard/UI geliştirmelerinde hızlı change-aware CI kullanılmalıdır.
- Kullanıcı açıkça istemedikçe Adaptive/AI Workbook Intelligence katmanı **şimdilik eklenmeyecek**. Mevcut deterministik semantik importer ile devam edilecek.

---

## 2. Güncel main / production checkpoint

Son doğrulanmış main SHA:

`297dd15f7dcfcf1a0851a5a87231b76bd5f47fd4`

PR #239 merge sonucudur: **Make CI and production deploy change-aware**.

Production workflow:

- Run: `33054987160`
- Sonuç: **SUCCESS**
- Mode: `backend`
- `SQLITE_RUNTIME|journal_mode=wal|busy_timeout=30000|integrity=ok`
- Production health check: **PASS**
- Kalıcı kanıt Issue #241: `IMS production deployment SUCCESS [backend]`

Bu noktadan sonra eski 20–30 dakikalık production acceptance zinciri her değişiklikte çalıştırılmıyor.

---

## 3. Change-aware CI/CD — TAMAMLANDI

PR #239 ile workflow dört moda ayrıldı:

- `ui`: template/static/dashboard görünüm değişiklikleri; hızlı syntax/smoke + production health.
- `backend`: importer dışı backend değişiklikleri; PR'da full suite, main'de hızlı backend smoke.
- `heavy`: importer, DB, migration veya ağır veri yolu değişiklikleri; gerçek IMS acceptance + gerekli DB/capacity güvenlik kapıları.
- `docs`: dokümantasyon-only.

Ağır `IMS Server Import Benchmark` daha önce PR #235 ile **manual-only** yapıldı; normal deploy sonrasında otomatik tetiklenmez.

Amaç: dashboard geliştirmelerinde dakikalarca gereksiz IMS acceptance beklememek. Güvenlik kapıları kaldırılmadı; değişikliğin riskine göre çalışıyor.

---

## 4. IMS import motorunun mevcut seviyesi

Mevcut import mimarisi deterministik fakat semantik/dinamik yapıdadır:

- workbook/sheet keşfi,
- sheet/header/column semantik sınıflandırması,
- temsilci / brick / ürün çözümü,
- raw staging,
- target / assignment,
- FACT / SUMMARY / official aggregate,
- competition import,
- reconciliation,
- atomik commit.

Sheet adı veya kolon sırası gibi sabit pozisyonlara mümkün olduğunca bağlı değildir. Gerçek `0`, aggregate kimlikleri, vacancy kimlikleri ve competition grain kuralları korunur.

Kullanıcı daha ileri “ChatGPT gibi tamamen yeni Excel yapısını yorumlayan adaptif inference” katmanını sordu; avantajları açıklandı ancak **şimdilik ertelendi**. Bu çalışma sırasında eklenmeyecek.

---

## 5. 7. hafta workbook kanıtı

Gerçek `Tayfun_7.Hafta_Subat_Brick_Analizi_.xlsx` dosyası güncel importer ile yerelde daha önce PASS verdi:

- Source / stored: `24,816 / 24,816`
- RAW: `25,104`
- FACT: `3,426`
- SUMMARY: `888`
- TARGET: `1,211`
- COMPETITION: `467,320`
- blockers: `0`
- reconciliation: `PASSED`
- local wall: yaklaşık `154.391s`
- competition stage: yaklaşık `36.781s`
- local peak working set: yaklaşık `402 MB`

Eski Issue #222 / #225 içindeki `481 unresolved representative` hatası **tarihsel ve eski importer sürümüne aittir**; PR #226 sonrasında representative/period grain düzeltildi. Yeni teşhiste o eski 481 hatasına geri dönülmemelidir, güncel log açıkça göstermedikçe kök neden olarak kullanılmamalıdır.

---

## 6. Canlıdaki asıl güncel problem — KRİTİK

Kullanıcı 7. hafta dosyasını canlı UI'dan yüklediğinde dashboard uzun süre döndü ve Chrome:

`ERR_CONNECTION_ABORTED`

gösterdi.

Bu durum iki kez tekrarlandı.

### İlk teşhis ve düzeltme

`gunicorn.conf.py` içinde `/ims/upload` POST sonrasında `worker.alive = False` ile worker zorla recycle ediliyordu. Bu davranış tarayıcı response'u almadan socketi kapatabiliyordu.

PR #238: **Keep IMS upload response stable**

- zorunlu `post_request` recycle kaldırıldı,
- test tersine çevrildi; bundan sonra `worker.alive = False` tekrar eklenirse FAIL olacak,
- normal Gunicorn `max_requests` recycling korundu.

Ancak bu düzeltmeden sonra **aynı ERR_CONNECTION_ABORTED tekrar oluştu**. Bu nedenle worker recycle yalnız ikincil problemdi; asıl mimari problem aşağıdadır.

---

## 7. Güncel kök neden

`app/ims.py` içindeki `/ims/upload` route'u hâlâ **senkron** çalışıyor.

Akış bugün şu şekilde:

1. HTTP POST dosyayı alıyor.
2. `ImportCoordinator.acquire(...)` aynı web isteği içinde tutuluyor.
3. Dosya kaydediliyor.
4. `IMSImportService(...).run(...)` aynı HTTP request içinde dakikalarca çalışıyor.
5. Official Brick Spread persist ve commit yapılıyor.
6. Ancak bütün bunlar bittikten sonra browser'a redirect/flash response dönüyor.

Yani kullanıcının mobil tarayıcısı ağır Excel importunun tamamını bekleyen uzun bir HTTP bağlantısına bağlı.

Production Gunicorn:

- en az 2 worker,
- `gthread`,
- 3 thread,
- `timeout=600`,
- `preload_app=False`.

Production makinesi küçük Oracle host:

- 2 OCPU,
- yaklaşık 1 GB RAM,
- yaklaşık 2 GB swap.

Önceki production acceptance ölçümlerinde gerçek IMS importu yaklaşık **740–760 MB peak RSS** seviyesine çıkmıştır. Bu nedenle web worker içinde pandas/openpyxl/import çalıştırmak hem uzun socket bağlantısı hem de RAM baskısı yaratmaktadır. Worker recycle kaldırılmış olsa bile worker/OS memory baskısı veya uzun request lifecycle nedeniyle tarayıcı bağlantısı tekrar kopabilmektedir.

**Sadece Gunicorn timeout yükseltmek çözüm değildir ve yapılmamalıdır.**

---

## 8. Kullanıcının onayladığı çözüm — SIRADAKİ ANA GÖREV

Kullanıcı açıkça şu davranışı istedi ve onayladı:

> Dosya alındıktan sonra ekranda uzun “yükleniyor” beklemesi olmasın. Sistem dosyayı kabul edip kullanıcıyı hemen serbest bıraksın. Import arka planda devam etsin. Bittiğinde bildirim alanına başarılı/başarısız bildirimi gelsin.

Bunu production-safe şekilde uygula.

### Hedef mimari

**Web request ağır import çalıştırmayacak.**

1. `/ims/upload` dosyayı doğrular ve güvenli staging klasörüne kaydeder.
2. Yıl/ay, dosya adı/hash, kullanıcı ve overwrite bilgisiyle kalıcı bir job oluşturur.
3. Job durumu başlangıçta `QUEUED` olur.
4. HTTP request mümkünse 1–2 saniye içinde IMS ekranına redirect/202 benzeri kısa response döner.
5. Ayrı **tekil IMS background worker** kuyruğu işler.
6. Worker mevcut `ImportCoordinator` single-writer kilidini kullanır.
7. Ağır `IMSImportService.run()` yalnız bu worker içinde çalışır.
8. Atomik transaction, reconciliation, fail-closed ve Official Brick Spread davranışı korunur.
9. Job `PROCESSING -> COMPLETED` veya `FAILED` olur.
10. UI/navbar notification alanı job sonucunu gösterir:
   - `7. Hafta IMS işleniyor`
   - `7. Hafta IMS başarıyla tamamlandı — raporu aç`
   - `IMS yüklenemedi — hata raporunu aç`
11. Kullanıcının sayfayı kapatması veya internet bağlantısının kopması importu etkilemez.

### Resource isolation zorunlu

Sadece background thread yapmak yeterli değildir. Heavy import web Gunicorn prosesinden ayrılmalıdır.

Tercih edilen production yaklaşımı:

- ayrı **systemd-managed single import worker process**,
- tek eşzamanlı import,
- mümkünse düşük CPU/IO önceliği,
- systemd `MemoryHigh` / makul `MemoryMax` veya eşdeğer sınırlarla web servisini OOM'dan koruma,
- import worker crash olursa web dashboard ayakta kalmalı,
- job recovery: PROCESSING worker beklenmedik ölürse stale job tekrar `FAILED`/recoverable hale getirilmeli,
- live DB yarım kalmamalı; mevcut atomik rollback korunmalı.

**Yeni Redis/Celery zorunlu değil.** Küçük tek sunucuda SQLite-backed queue + systemd worker daha az kaynak ve operasyonel karmaşıklıkla tercih edilebilir. Ancak job claim atomik olmalı ve aynı job iki worker tarafından alınmamalıdır.

---

## 9. Veri modeli / queue için önerilen minimal yaklaşım

Mevcut mimariyi bozmadan minimal yeni model/tablo oluştur:

`IMSImportJob` (veya eşdeğer):

- `id`
- `status`: `QUEUED | PROCESSING | COMPLETED | FAILED`
- `file_name`
- `stored_file_name` / `file_path`
- `source_hash`
- `year`
- `month`
- `clear_before_import` / overwrite flag
- `uploaded_by`
- `ims_upload_id` nullable
- `queued_at`
- `started_at`
- `completed_at`
- `heartbeat_at` nullable
- `error_message` nullable
- `result_summary` nullable JSON/text

Queue claim transaction-safe olmalı. Tek worker olsa bile duplicate claim önlenmeli.

Mevcut `IMSUpload` audit modeli business import sonucu olarak kalabilir; queue state ile karıştırılmaması daha temizdir.

---

## 10. UI / bildirim davranışı

Kullanıcı uzun spinner görmek istemiyor.

Upload submit sonrası:

- dosya staging'e kabul edilirse hemen `Dosya alındı, IMS arka planda işleniyor.` mesajı,
- IMS Merkezi açık kalabilir / kullanıcı dashboard'a geçebilir,
- navbar mevcut notification alanı kullanılabiliyorsa oraya entegre et; yeni ağır frontend framework ekleme,
- hafif polling endpoint (ör. 10–20 sn) veya sayfa navigation sırasında server-rendered unread notification kullanılabilir,
- polling çok sık olmayacak,
- import bitince success/fail notification,
- rapor linki ilgili `IMSUpload`/manager report ekranına gider.

Notification sistemi mevcutsa onu genişlet; paralel ikinci bir bildirim sistemi oluşturma.

---

## 11. Mevcut 7. hafta kaydı — ŞÜPHELİ / DOKUNMA

Kullanıcı ilk/ikinci crash sonrasında dashboard'u yeniden açınca 7. hafta importu ekranda `Tamamlandı`, `15/15` vb. göründü.

Bu kayıt **manuel eklenmedi**; büyük olasılıkla tarayıcı bağlantısı koparken server-side import transaction devam edip commit oldu.

Ancak bu kaydın canlı DB'de güncel importer ile tam fingerprint/reconciliation kanıtı henüz alınmadığı için **kesin doğru kabul edilmemelidir**.

Kullanıcıya üçüncü kez upload yapmaması söylendi.

### Async mimari deploy edildikten sonraki doğrulama

Aynı 7. hafta workbook'u **bir kez** güvenli overwrite/reprocess ile yeniden çalıştır.

Doğrula:

- job COMPLETED,
- browser bağlantısı düşmüyor / kullanıcı beklemiyor,
- source == stored,
- reconciliation PASSED,
- unresolved representative = 0,
- unresolved product = 0,
- invalid metric = 0,
- row error = 0,
- duplicate/conflict blocker = 0,
- expected RAW/FACT/SUMMARY/TARGET/COMPETITION business counts/fingerprint tutarlı,
- manager IMS report PASS.

Temiz PASS sonrası import geliştirmesi kapatılıp dashboard çalışmalarına geçilecek.

---

## 12. Test stratejisi — KREDİ / ZAMAN KAYBI YAPMA

Kullanıcı uzun testlerin geliştirme süresini ve Codex 5-saatlik kullanım hakkını tükettiğini açıkça belirtti.

Bu görevde:

1. Geliştirme sırasında yalnız hedefli unit/contract testleri.
2. Async queue/job claim/worker crash/route immediate-return/atomic rollback testleri ekle.
3. PR sınıflandırması importer/DB değişikliği nedeniyle `heavy` olabilir; PR'da gerekli tam güvenlik suite **bir kez** çalışsın.
4. Aynı full suite'i main push'ta tekrar çalıştırma; mevcut change-aware workflow'u kullan.
5. Standalone server benchmark'ı otomatik başlatma; manual-only kalmalı.
6. Production heavy acceptance yalnız bu importer mimari değişikliğinde gerektiği kadar çalışsın.
7. UI/dashboard geliştirmesine geçildiğinde `ui` hızlı hattı kullanılmalı.
8. GitHub Actions durumunu saniyelik/persistently poll etme; gereksiz tekrar sorgularından kaçın.

Güvenlik eşiklerini hız için gevşetme.

---

## 13. Async çözüm için zorunlu regression testleri

En az aşağıdakileri kapsa:

- `/ims/upload` ağır `IMSImportService.run()` çağırmadan hızlı döner.
- Upload route yalnız staging + queue kaydı oluşturur.
- Aynı anda iki upload gelirse single-writer semantics bozulmaz.
- Queue claim atomiktir; aynı job iki kez işlenmez.
- Worker `IMSImportService.run()` çağırır ve mevcut business sonuçlarını değiştirmez.
- Import başarısızsa job FAILED, live business DB yarım kalmaz.
- Worker ölürse web Gunicorn servisi çalışmaya devam eder.
- Success job `IMSUpload` sonucu ve notification ile ilişkilidir.
- Existing OfficialBrickSpread persist işlemi başarı durumunda korunur.
- `worker.alive = False` tekrar eklenemez.
- Web upload response uzun import süresine bağlı değildir.
- Stale PROCESSING recovery bounded/fail-safe çalışır.

---

## 14. Deployment sırasında dikkat

- Branch -> PR -> CI -> merge -> production gate sırasını koru.
- Production acceptance fail ise restart/worker enable gibi riskli son adımı yapma.
- Önce migration/model, sonra worker service file/install script, sonra web route.
- systemd worker deploy sırasında enable/start doğrulanmalı.
- Web service ve worker service health ayrı raporlanmalı.
- Worker logları mevcut `ims-kontrol` benzeri operasyon akışına entegre edilebiliyorsa et; kullanıcı terminal karmaşıklığı istemiyor.
- Concurrency group nedeniyle gereksiz main push production deploy'u iptal edebilir; geçici dosya/placeholder commit yapma.

---

## 15. Şu an yapılmaması gerekenler

- 7. hafta IMS'yi UI'dan tekrar tekrar yükleme.
- Gunicorn timeout'u sadece yükseltip sorunu gizleme.
- Heavy importu Flask background thread'e atıp aynı Gunicorn processinde bırakma.
- Redis/Celery gibi yeni altyapıyı gereksiz yere ekleme.
- Eski 481 unresolved benchmark hatasını güncel problem sanma.
- Import validation/reconciliation eşiklerini gevşetme.
- Adaptive AI workbook inference özelliğini bu göreve karıştırma.
- Dashboard business logic / prime / hedef hesaplarına dokunma.

---

## 16. Çalışma ortamına verilecek başlangıç promptu

Aşağıdaki prompt yeni çalışma ortamında kullanılabilir:

> Repo `muratarslan35/ims-performance-manager` içinde önce `WORKSPACE_HANDOFF_CURRENT.md` dosyasını tamamen oku ve bunu tek aktif checkpoint kabul et. Eski `PROJECT_WORK_PROGRESS.md` bölümlerine geri dönme; yalnız tarihsel kanıt gerektiğinde kullan. Güncel problem `/ims/upload` route'unun gerçek IMS importunu aynı HTTP/Gunicorn worker içinde senkron çalıştırması ve küçük production hostta tekrar eden `ERR_CONNECTION_ABORTED` oluşturmasıdır. Kullanıcının onayladığı çözümü uygula: dosyayı hızlı şekilde staging'e al, kalıcı SQLite-backed import job oluştur, web response'u hemen döndür, ağır `IMSImportService.run()` işlemini ayrı systemd-managed single background worker'a taşı, mevcut ImportCoordinator/atomic transaction/reconciliation/fail-closed/OfficialBrickSpread kurallarını koru, worker'ı web servisinden RAM açısından izole et ve import tamamlanınca mevcut navbar notification alanına success/fail bildirim gönder. Önce hedefli testlerle ilerle; change-aware CI'yi bozma; full/heavy testleri yalnız gerekli kapıda bir kez çalıştır. Async çözüm production PASS olmadan 7. hafta IMS'yi tekrar yükleme. Sonra aynı 7. hafta dosyasını bir kez safe overwrite ile doğrula ve temiz PASS sonrası import geliştirmesini kapatıp dashboard'a geç.

---

## 17. Son durum özeti

**CI/CD hız sorunu çözüldü.**  
**Worker post_request recycle hatası çözüldü ancak ana çökme devam ediyor.**  
**Ana kök neden: ağır IMS importu hâlâ web HTTP request/Gunicorn worker içinde senkron.**  
**Onaylı sonraki çözüm: persistent queue + ayrı single systemd import worker + notification.**  
**7. hafta mevcut kaydı kesin doğrulanmış sayılmıyor; async çözümden önce tekrar upload yapılmayacak.**
