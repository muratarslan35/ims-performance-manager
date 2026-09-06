# IMS Performance Manager — 6 Eylül 2026 Canonical Workspace Handoff

> Tarih: **6 Eylül 2026 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Durum: **KANONİK / KİLİTLİ**  
> Amaç: Yeni çalışma alanı / Codex bu dosyayı okuyarak mevcut sistemi bozmadan **ardışık IMS yükleme aşamasından** devam etsin.
>
> Bu dosya `WORKSPACE_HANDOFF_2026-09-01.md` dosyasının devamı ve daha güncel kanonik kaydıdır. Çelişki halinde **bu dosya esas alınır**.

---

## 1. DEĞİŞTİRİLMEYECEK / KİLİTLİ ANA SÖZLEŞMELER

Aşağıdaki kurallar kullanıcı açıkça aksini istemedikçe **değiştirilemez**:

- Mevcut mimari, hesap motorları, dashboard hesapları ve veri öncelikleri korunacak.
- **P2 > P1 > IMS** veri önceliği kesinlikle korunacak.
- Hedef, gerçekleşen, kutu/TL, realizasyon, prim, fiyat dönüşümü ve yuvarlama formülleri değiştirilmeyecek.
- Production result / IMS / target okuma yöntemi değiştirilmeden mevcut authority sözleşmeleri korunacak.
- `BOS` ve `BOŞ` ayrı kimliklerdir; `BOSTANCI` normal değerdir.
- Numeric `0` gerçek veridir; blank/null ile karıştırılmayacak.
- Fail-closed import/validation sözleşmeleri gevşetilmeyecek.
- SQLite `WAL` ve `busy_timeout=30000` korunacak.
- IMS import job `PROCESSING` iken deploy/restart yapılmayacak.
- Full ilgili CI yeşil olmadan merge yapılmayacak.
- Production acceptance/deploy PASS olmadan "tamamlandı" denmeyecek.
- Canlı DB üzerinde ağır benchmark yapılmayacak.
- UI işi istenmişse mümkün olduğunca template/CSS/JS ile sınırlı kalınacak; business logic etkilenmeyecek.
- Snapshot/cache katmanları **yalnız hızlandırma/read-model katmanıdır**; veri kaynağı veya hesap otoritesi değildir.
- Snapshot üretimi başarısız olursa geçerli business data bozulmamalı; güvenli mevcut hesap/fallback yolu korunmalı.

### Kullanıcı talimatı

> Sistemin hiçbir verisini bozma. Düzenlediğimiz ayarlar, yapılar ve hesaplamalar kilit kalsın. IMS yüklemesi aşamasına geçiyoruz; bundan sonra IMS'leri ardışık olarak yükleyip doğrulayacağız.

---

## 2. GÜNCEL MAIN / PRODUCTION

6 Eylül 2026 itibarıyla #521 merge sonrası main commit:

`c22f1f3a522ef85fe123adf6e6b2809bd6d48fdd`

PR #521 production workflow run `34050437358` sonucu:

- Main smoke (import): **PASS**
- Change-aware production deploy: **PASS**
- Publish compact deployment evidence: **PASS**
- Enforce production deployment result: **PASS**
- Deploy production (import): **SUCCESS**

Bu deploy #520 kodunu da içerdiği için **temsilci kalıcı DB snapshot sistemi + IMS snapshot ilerleme barı canlıdadır**.

---

## 3. TEMSİLCİ DÖNEM WORKSPACE — PR #498

Temsilci ekranı dönem yapısı standartlaştırıldı:

- `6 Aylık | YILLIK YTD`
- `Aylık | Q1 | Q2 | Q3 | Q4`

Eski AI dönemleri `Aylık / 3 Aylık / 6 Aylık` kaldırıldı.

Eklenen servis:

- `app/services/representative_period_workspace.py`

Eklenen CSS:

- `app/static/css/representative-period-workspace.css`

Bu dönem yapısı artık kilit kabul edilir; hesaplama anlamı değiştirilmemeli.

---

## 4. BÖLGE MÜDÜRÜ TARİHSEL AY SEÇİCİ — PR #500

Region manager historical month selector sayfa hero alanına taşındı.

Bu değişiklik UI yerleşimidir; backend hesap mantığını değiştirmedi.

---

## 5. TEMSİLCİ DÖNEM BUTONLARI / CLIENT-SIDE GEÇİŞ — PR #502 ve #508

Temsilci ekranında dönemler tek sayfada hazır payload üzerinden client-side değişecek şekilde düzenlendi.

- Aylık / Q1 / Q2 / Q3 / Q4 / 6 Aylık / YTD butonları sayfa yenilemeden değişir.
- AI bölümü sayfanın altına taşındı.
- Ürün kutu analizi dark-mode renkleri normalize edildi.
- PR #508 ile global `[data-percent]` JS çakışması giderildi; temsilci butonları `data-realization-percent` kullanır.

Buton etiketleri:

- `6 Aylık`
- `YILLIK YTD`
- `Aylık`
- `Q1`
- `Q2`
- `Q3`
- `Q4`

Bu etiket/dönem sözleşmesi korunacak.

---

## 6. AI GERÇEK VERİ KAPSAMI — PR #504

Sentetik `EKİP 4` aggregate AI kaldırıldı.

Korunan gerçek analizler:

- ardışık IMS karşılaştırması,
- aylık ürün/rakip değişimleri,
- region manager tarafında gerçek temsilci sonuçlarından şehir/bölge performansı.

AI dönemleri mevcut workspace ile hizalandı:

- `monthly`
- `q1`, `q2`, `q3`, `q4`
- `half_year`
- `yearly`

Sentetik veri üretimi geri eklenmemeli.

---

## 7. BÖLGE KUTU AUTHORITY DÜZELTMESİ — PR #506

Nisan 2026+ açık IMS dönemlerinde bölge kutu authority tutarsızlığı giderildi.

Canlı audit örneği Diyarbakır / Brimoder:

- hedef: 136.547 TL
- gerçekleşen: 122.479 TL
- realizasyon: %90
- same-price hedef yaklaşık 165 kutu
- actual 148 kutu
- gap yaklaşık -17 kutu

Production audit:

- 11 bölge × 7 ürün = **77 satır**
- failures = `[]`

`verify_runtime.py` içinde `region.box_authority_all_regions` kontrolü vardır.

Bu authority sözleşmesi kilittir.

---

## 8. BÖLGE KALICI DB SNAPSHOT MİMARİSİ — PR #511

Bölge ekranı kalıcı, upload-versioned DB snapshot modeline taşındı.

Ana servis:

- `app/services/persistent_region_snapshot_service.py`

Tablolar:

- `manager_region_snapshot_sets`
- `manager_region_snapshots`

Durumlar:

- `BUILDING`
- `ACTIVE`
- `SUPERSEDED`
- `FAILED`

Temel sözleşme:

- Partial BUILDING set kullanıcıya gösterilmez.
- Kullanıcı yalnız tamamlanmış ACTIVE set okur.
- Yeni set tamamen hazır olmadan eski ACTIVE görünür kalır.
- Kaynak identity IMS + production upload kimliğiyle sürümlenir.
- Backend/heavy deploy sonrası gerekli force rebuild yapılabilir.
- UI-only deploy snapshot rebuild yapmaz.

PR #511 ile backend/heavy deploylarda region snapshot otomatik refresh altyapısı kuruldu.

Bu mimari artık temsilci snapshot için de referans modeldir.

---

## 9. TEMSİLCİ KISA SÜRELİ PROCESS CACHE — PR #512 ve #514

Temsilci ağır alt sorgularında mevcut process-level cache korunmaktadır.

İlgili sınıf:

- `app/cache/representative_analysis_cache.py`

Kaynak-kimlikli prefixler:

- `rep-market:`
- `rep-intelligence:`

PR #512 önce 8 günlük retention ekledi.

PR #514 ile 8 günlük takvim üst sınırı kaldırıldı:

- source-keyed representative cache elapsed-day ile expire olmaz,
- yeni upload/source identity yeni key oluşturur,
- process restart/deploy, explicit clear veya LRU eviction ile RAM cache kaybolabilir,
- diğer generic cache keyleri maksimum 120 saniye sınırında kalır.

Bu RAM cache **kalıcı snapshot değildir**; yalnız yardımcı hızlandırmadır.

---

## 10. TEMSİLCİ ÜRÜN KUTU ANALİZİ CSS — PR #516

Temsilci ekranındaki ürün bazlı kutu analizinde satırın tamamına yanlış kırmızı/yeşil miras verilmesi giderildi.

Artık:

- ürün adı,
- temsilci satışı,
- rakip kutu,
- toplam pazar

normal sayfa metin rengini kullanır.

Sağ realizasyon semantik renkleri sayfa geneliyle hizalıdır:

- güçlü → yeşil
- takip → sarı
- öncelikli → kırmızı

Açık/koyu tema uyumu korunacak.

Bu yalnız UI/CSS değişikliğidir.

---

## 11. TEMSİLCİ KALICI DB SNAPSHOT MİMARİSİ — PR #520

30–35 saniyelik temsilci ilk-açılış gecikmesinin ana nedeni, sayfa request sırasında 7 dönemlik workspace + market/rakip + AI read-modelinin tekrar kurulmasıydı.

#520 ile bölge ekranındaki yöntem temsilci tarafına da uygulandı.

### Temel hedef

Temsilci sayfasında aşağıdaki hazır read-model artık kalıcı snapshot üzerinden okunabilir:

- Aylık
- Q1
- Q2
- Q3
- Q4
- 6 Aylık
- YTD
- ürün sonuçları
- market/rakip analizi
- annual realization
- AI read-modeli

### Ana servis

- `app/services/persistent_representative_snapshot_service.py`

### Ana sözleşme

- Mevcut hesap servisleri **değiştirilmedi**; onların çıktısı saklanır.
- Snapshot yeni authority değildir.
- Yeni IMS/source identity ile yeni generation oluşturulur.
- BUILDING set kullanıcıya verilmez.
- Önceki ACTIVE set yeni generation hazır olana kadar görünür kalır.
- Yeni set tamamen hazır olunca atomik ACTIVE olur.
- Kullanıcının ilk tıklaması snapshot üretimini başlatmak zorunda değildir.
- Background worker temsilci snapshotlarını kullanıcı gelmeden hazırlar.
- İlk deployment/bootstrap aşamasında ACTIVE generation yoksa web aktivasyonundan önce bootstrap edilebilir.
- Backend hesap/read-model değişikliklerinde background refresh yapılabilir.

### Worker davranışı

`ims_import_worker.py`:

- worker startup'ta latest period durable read-model warm-up yapabilir,
- IMS import tamamlandıktan sonra dashboard + temsilci snapshot warm-up başlatır,
- user request'e bağımlı değildir.

### Önemli

#520 kendi heavy production deploy run'ında cancellation gördü; ancak #521 main deploy'u #520 kodunu içererek production'a **SUCCESS** ile geçti. Bu nedenle #520 mimarisi şu an canlı kabul edilir.

---

## 12. IMS YÜKLEME + SNAPSHOT PROGRESS — PR #521

IMS ekranındaki gerçek progress bar snapshot hazırlık sürecini de kapsayacak şekilde genişletildi.

Mevcut progress altyapısı:

- `app/services/ims_progress_store.py`
- `app/routes/ims_progress.py`
- frontend polling: `/ims/progress`

Progress kayıtları ana IMS SQLite transaction dışında atomik JSON kanalında tutulur; import atomicity bozulmaz.

### Yeni görünür akış

- **%0–90:** gerçek workbook/import aşamaları
- **%92–94:** bölge snapshotlarının gerçek `done/total` ilerlemesi
- **%95:** dashboard snapshot hazırlığı
- **%96–99:** temsilci snapshotlarının gerçek `done/total` ilerlemesi
- **%100:** IMS + ilgili analiz ekranları hazır

Son snapshot aşamasında kullanıcı mesajı:

- **`Veriler ekrana aktarılıyor`**

Temsilci snapshot ilerlemesinde gerçek completed/total ve hızdan ETA hesaplanabilir; random/sahte progress kullanılmaz.

Başarılı final mesaj:

- **`IMS yüklemesi ve analiz ekranları hazır`**

### Kilit davranış

%100 mümkün olduğunca business import + read-model hazırlığının tamamlanmasını ifade eder.

Snapshot acceleration başarısızlığı geçerli IMS business-data importunu bozmamalı; güvenli fallback korunmalıdır.

PR #521:

- Locked Canonical Contracts: **PASS**
- Import full suite: **PASS**
- 50-upload scale probe: **PASS**
- Main smoke (import): **PASS**
- Production deploy: **SUCCESS**

Main commit:

`c22f1f3a522ef85fe123adf6e6b2809bd6d48fdd`

---

## 13. SNAPSHOT / CACHE KATMANLARININ NET AYRIMI

### Bölge

Kalıcı DB snapshot vardır. Kullanıcı ağır region hesaplarını request-time tekrar üretmez.

### Temsilci

Kalıcı DB snapshot vardır. Ek olarak alt sorgular için process-level RAM cache devam eder.

### Dashboard

Persistent dashboard snapshot / warm-up yolu korunur.

### Genel kural

Snapshotlar:

- hızlandırma katmanıdır,
- business-data kaynağı değildir,
- formül değiştirmez,
- source identity ile yenilenir,
- eski ACTIVE veri yeni generation hazır olana kadar güvenli görünür kalabilir.

---

## 14. PERFORMANS BEKLENTİSİ

Temsilci sayfasının eski 30–35 saniyelik request-time maliyetini kaldırmak için persistent representative snapshot devrededir.

Yeni IMS sonrası snapshot hazırlama süresi şunlara bağlıdır:

- IMS ve competition veri boyutu,
- temsilci sayısı,
- geçmiş dönem kapsamı,
- CPU,
- disk/SQLite I/O,
- RAM yetersizse swap etkisi.

Kullanıcı açısından kritik sözleşme:

- snapshot hazırlığı kullanıcı ilk tıklamasına bırakılmamalı,
- worker/background warm-up yapmalı,
- progress bar bunun durumunu göstermeli,
- hazır ACTIVE snapshot varsa ekran hızlı açılmalı.

RAM artışı tek başına ana hızlandırıcı değildir; CPU ve I/O daha doğrudan etkili olabilir.

---

## 15. SONRAKİ ANA FAZ — ARDIŞIK IMS YÜKLEMELERİ

Artık ana geliştirme fazından ardışık IMS yükleme/doğrulama fazına geçiliyor.

Her IMS yüklemesinde aşağıdaki sıra korunmalı:

1. Dosya yüklenir; mevcut fail-closed import kuralları uygulanır.
2. Dosyanın week/month/year identity'si doğrulanır.
3. IMS import atomic olarak tamamlanır.
4. Source reconciliation ve official brick spread mevcut sözleşmeyle tamamlanır.
5. Bölge snapshotları hazırlanır.
6. Dashboard snapshot/warm-up hazırlanır.
7. Temsilci snapshotları background worker tarafından hazırlanır.
8. IMS ekranındaki progress gerçek ilerlemeyi gösterir.
9. %100 sonrası read-only acceptance yapılır.
10. P2 > P1 > IMS, hedef, actual, kutu/TL, realizasyon ve representative/region totals kontrol edilir.
11. PASS olmadan sonraki IMS'e geçilmez.

### Yükleme sırasında kesinlikle yapılmayacaklar

- Formül değiştirmek.
- Authority önceliğini değiştirmek.
- Yeni parser davranışını kanıtsız gevşetmek.
- Eksik/uyumsuz satırı sessizce atlamak.
- Numeric 0'ı blank kabul etmek.
- BOS/BOŞ kimliklerini birleştirmek.
- Snapshot sonucu ile business DB'yi overwrite etmek.
- IMS PROCESSING iken deploy/restart yapmak.

---

## 16. YENİ ÇALIŞMA ALANI İÇİN BAŞLANGIÇ PROMPTU

> GitHub repo `muratarslan35/ims-performance-manager`. Önce `WORKSPACE_HANDOFF_2026-09-06.md` dosyasını oku ve bunu kanonik/kilitli sözleşme kabul et. Sistemin mevcut P2 > P1 > IMS, hedef, production, kutu/TL, realizasyon, prim, yuvarlama, BOS/BOŞ, fail-closed import, SQLite WAL/busy_timeout ve snapshot mimarisini değiştirme. Bölge ve temsilci kalıcı DB snapshot sistemleri yalnız hızlandırma read-model katmanıdır; hesap otoritesi değildir. PR #521 sonrası production commit `c22f1f3a522ef85fe123adf6e6b2809bd6d48fdd` ve deploy PASS kabul edilmiştir. Bundan sonra ardışık IMS yüklemelerine geçiyoruz. Her IMS'i sırayla yükle, progress/snapshotların tamamlanmasını bekle, read-only acceptance yap ve PASS olmadan sonraki IMS'e geçme. IMS PROCESSING iken deploy/restart yapma. Full ilgili CI ve production acceptance PASS olmadan tamamlandı deme.

---

## 17. KISA DURUM ÖZETİ

- Bölge persistent snapshot: **LIVE / LOCKED**
- Temsilci persistent snapshot: **LIVE / LOCKED**
- Temsilci process cache no-calendar-expiry: **LIVE**
- Dashboard persistent warm-up: **LIVE**
- Temsilci dönem workspace Aylık/Q1-Q4/6 Aylık/YTD: **LIVE / LOCKED**
- Temsilci kutu analiz CSS/realizasyon renkleri: **LIVE**
- IMS gerçek progress + snapshot progress: **LIVE**
- PR #521 production deploy: **PASS**
- Güncel main: `c22f1f3a522ef85fe123adf6e6b2809bd6d48fdd`
- Sıradaki iş: **ARDIŞIK IMS YÜKLEMELERİ VE HER YÜKLEME SONRASI ACCEPTANCE**
