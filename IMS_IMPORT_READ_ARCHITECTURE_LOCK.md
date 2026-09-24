# IMS Performance Manager — Import ve Okuma Mimarisi Kanonik Kilidi

Durum: **KİLİTLİ / PRODUCTION KANONİK**  
Tarih: **24 Eylül 2026**  
Sahip/onay mercii: **muratarslan35**

Bu belge IMS Performance Manager'ın bundan sonraki temel çalışma sözleşmesidir. Amaç yeni özellik eklemek değil; çalışan import, doğrulama, snapshot ve okuma mimarisini sabitlemektir.

## 1. Nihai hedef

Kullanıcı açısından sistemin tek normal akışı şudur:

**Dosya yüklenir → otomatik doğrulanır → veriler tek seferde işlenir → bütün read-model/snapshot paketleri hazırlanır → atomik olarak yayınlanır → ekranlar hazır veriyi okur.**

Normal kullanıcı isteği sırasında ağır IMS hesabı, Excel okuması veya yeniden aggregation yapılmaz.

Bir import doğrulanamıyorsa yeni/yarım veri canlıya verilmez. Önceki doğrulanmış generation görünür kalır. Sistem bu nedenle **fail-closed** çalışır.

## 2. Değiştirilemez import akışı

1. Upload kabul edilir ve durable import işi oluşturulur.
2. Devam eden iş kesilmez; yeni iş gerekiyorsa kuyruğa alınır.
3. Workbook önce preflight + semantic discovery katmanından geçer.
4. Sheet adı/kolon pozisyonu kör sabit okumayla değil, mevcut semantic/compatibility sözleşmeleriyle çözülür.
5. RAW/FACT/SUMMARY/TARGET/competition ve ilgili authority kayıtları tek kabul edilen kaynak kimliğine bağlanır.
6. Import transaction/reconciliation tamamlanmadan upload COMPLETED kabul edilmez.
7. Dashboard, Bölge ve Temsilci read-model generation'ları aynı kaynak kimliği için hazırlanır.
8. Türkiye pazar/rakip payload'ı dashboard read-modeline tam olarak eklenir; yalnız özet ranking payload'ı ile üzerine yazılamaz.
9. Bölge read-modeli market + AI enrichment dahil hazırlanır.
10. Tüm zorunlu generation'lar hazır olmadan publication 100% / ready sayılmaz.
11. Yeni hafta/tarih UI'da ancak publication tamamlandıktan sonra görünür.
12. Publish atomiktir; yarım generation kullanıcıya açılmaz.

Bu sıra değiştirilemez.

## 3. Kaynak otoritesi

### 3.1 Aylık sonuç kaynağı

Her ay bağımsız değerlendirilir:

**P2 üretim > P1 üretim > IMS**

Üretim daha sonra geldiğinde aynı ayın IMS katkısına eklenmez; **o ayın IMS sonucunun yerine geçer**.

Geç gelen üretim dosyası geçmiş ayı günceller ve o aya bağlı dashboard/bölge/temsilci/Q/YTD read-model bağımlılıkları durable queue üzerinden yenilenir.

### 3.2 TL otoritesi

- Açık IMS ayında TL hedef/gerçekleşen: resmi IMS authority.
- Final üretim bulunan ayda: P2/P1 üretim authority.
- Kutu/bakiye/rakip verisinden TL sonucu uydurulmaz.

### 3.3 Kutu hesabı

Nisan 2026 ve sonrası açık IMS dönemlerinde:

- hedef kutu = resmi hedef TL / dönem için geçerli ürün birim fiyatı
- gerçekleşen kutu = resmi gerçekleşen TL / dönem için geçerli ürün birim fiyatı
- kutu farkı = gerçekleşen kutu - hedef kutu
- yuvarlama = merkezi TLBoxCalculationService / ROUND_HALF_DOWN

Dönem birim fiyatı geçmişe dönük mutable master fiyattan okunmaz. Aktif ay başladıktan sonra yapılan fiyat değişikliği bir sonraki IMS döneminden itibaren geçerlidir.

P1/P2 ile kapanan dönemlerin final kutu/TL sonuçları sonradan formül değişikliğiyle yeniden yazılmaz.

### 3.4 Kota çıkış

Üretim otoritesine göre ulusal düzeyde gerçek satış bulunmayan ürün/ay kota çıkış kabul edildiğinde ilgili ürünün TL hedefi %100 kapanmış sayılır. Bu sonuç temsilci, bölge, dashboard ve Q tüketicilerinde aynı authority üzerinden okunur. Aynı kural için ekran bazlı alternatif hesap üretilemez.

## 4. Kalıcı okuma mimarisi

### Dashboard
Normal route, PersistentDashboardSnapshotService tarafından yayınlanmış hazır payload'ı okur.

### Türkiye Pazar Analizi
Tam competition_analysis read-modeli dashboard publication ile birlikte taşınır. Route içinde MarketAnalysisService ile ağır canlı hesap yapılmaz. Rekabet verisi olan bir IMS haftasında payload'ın eksik yayınlanması kabul edilmez.

### Bölge
PersistentRegionSnapshotService hazır region generation'ını okur. Region request'i içinde RegionPerformanceService, RegionMarketService veya AI builder ile yeni ağır hesap başlatılmaz.

### Temsilci
PersistentRepresentativeSnapshotService hazır temsilci paketini okur. Kullanıcı isteklerinde her temsilci için tekrar DB aggregation yapılmaz.

### Geçmiş dönem
Geçmiş production/IMS görünümü source-identity uyumlu durable read-modelden okunur. Geçmiş aya geçiş dashboard'a kaçış üretmemelidir. Eksik generation varsa request içinde limitsiz ağır rebuild yapılmaz; durable compatibility/queue mekanizması kullanılır.

### Atomik görünürlük
Dashboard + region + representative generation'ları aynı kabul edilen kaynak durumuna ulaşmadan publication tamamlanmış sayılmaz.

## 5. Türkiye sıralama kuralları

### Alt tablo — IMS Türkiye Sıralaması
- yalnız seçili ay
- temsilci bazlı **₺ realizasyon oranı**
- o ay için P2 > P1 > IMS

### Üst tablo — Yıllık Ürün Bazlı Türkiye Sıralaması
- Ocak'tan seçili aya kadar YTD
- ürün bazında kutu toplamı
- her ay kendi içinde P2 > P1 > IMS
- üretim sonradan gelirse o ayın IMS katkısı değiştirilir, üzerine eklenmez

Bu iki tablo birbirine çevrilemez.

## 6. Rekabet / market read-model kuralı

Ranking veya başka bir dashboard refresh işlemi, mevcut full market payloadını düşüremez.

Publication öncesi:
- national competition read-model mevcut olmalı,
- region market read-modeli beklenen tüm bölgelerde hazır olmalı,
- önceki-ay competitor karşılaştırması gerekli dönemde hazır olmalı,
- aylık region ürün satırlarında zorunlu kutu farkları eksik kalmamalı.

24 Eylül canlı kabulünde Eylül için:
- source: 38. hafta CURRENT
- regions: 11/11
- market_ready: 11/11
- previous_competitor_ready: 11/11
- box_ready: 11/11

## 7. Performans ve eşzamanlılık sözleşmesi

- SQLite WAL korunur.
- busy_timeout=30000 korunur.
- Import/snapshot yazıları single-writer / durable queue modeliyle seri hale getirilir.
- Kullanıcı request'leri snapshot/read-model okur; aynı hesap 200 kullanıcı için 200 kez çalıştırılmaz.
- Ağır rapor/export işleri ayrı report worker'da çalışır.
- Deploy aktif import/publication varken işi kesmez.
- Snapshot yenilemesi paket/bulk yaklaşımını korur; temsilciler gereksiz tek tek canlı request zincirinde hesaplanmaz.
- Yüzde 100 progress yalnız zorunlu publication bileşenleri gerçekten hazırsa gösterilir.

## 8. Kimlik ve veri bütünlüğü kuralları

- Gerçek sayısal 0, boş/verisiz değildir.
- BOS ve BOŞ ayrı kimliklerdir.
- BOSTANCI vacancy değildir.
- Temsilci ayrıldığında tarihsel isim/veri korunur; yeni kişi yeni kimliğiyle bağlanır.
- Ankara dahil boş/boş kadro kayıtları canonical roster kapsamından keyfi olarak düşürülemez.
- National/region official aggregate varsa temsilci toplamı onun yerine alternatif authority olarak kullanılamaz.
- Aynı ürün/ay/temsilci için iki farklı kaynak aynı anda final katkı yapamaz.

## 9. 22–24 Eylül 2026 son stabilizasyon değişiklikleri

- **PR #973** — yarım kalan Temmuz P2 temsilci snapshot işi resumable hale getirildi; production/historical refresh zinciri korunarak tamamlandı.
- **PR #1084** — alt Türkiye sıralaması aylık ₺ realizasyon, üst ürün sıralaması YTD kutu toplamı olarak ayrıldı.
- **PR #1089** — Ağustos publication gate yalnız dashboard + region + representative generation doğrulaması sonrası güvenli finalize edilir hale getirildi.
- **PR #1092** — ranking refresh'in full pazar/rakip competition_analysis payloadını silmesi engellendi.
- **PR #1093** — uzun production read-model yenilemelerinde SSH keepalive eklendi.
- **PR #1096** — tamamlanan dönem read-modelleri REUSED, eksik dönemler resumable rebuild olacak şekilde yenileme akışı düzeltildi.
- **PR #1098** — yalnız eksik unit_difference satırlarında resmi bölge TL + dönem fiyatı ile aylık kutu farkı backfill edildi; sağlıklı bölgelerin mevcut değerleri korunur.
- Son Eylül canlı kabulü: market_ready=11, previous_competitor_ready=11, box_ready=11, MARKET_READ_MODEL_REPAIR=PASS.

Ayrıntılı tarihsel geliştirme günlüğü PROJECT_WORK_PROGRESS.md içinde tutulmaya devam eder.

## 10. Değişiklik kilidi

Bu doküman ve import/read-model çekirdeği normal geliştirme alanı değildir. Değişiklik ancak:
1. sorun kullanıcıya açıklanır,
2. etkilenecek kural/dosyalar açıkça listelenir,
3. **Murat Arslan açık onay verir**,
4. onay PR üzerinde repo sahibi tarafından review/comment olarak kayda geçirilir,
5. locked regression + ilgili full CI PASS olur,
6. production acceptance PASS olur
ise yapılabilir.

Onay başka bir PR'a veya başka bir kapsama taşınamaz.

Amaç bundan sonra sistemi sürekli yeniden tasarlamak değil, bu sözleşmeyi koruyup **dosya yükle → otomatik doğrula → doğru aktar → atomik yayınla** akışını sürdürmektir.
