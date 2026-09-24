# IMS Performance Manager — Kanonik Değişim Kilidi

Durum: **KİLİTLİ**
Başlangıç referansı: `24416e4503412f033a35806d8b40f42ecea8ccbe` (PR #450 sonrası main)

Bu dosyada listelenen kurallar ve bunları uygulayan kritik kod yolları artık varsayılan olarak değiştirilemez. Bir görev bu alanlardan herhangi birini değiştirmeyi gerektiriyorsa değişiklik yapılmadan önce kullanıcıya etkisi, gerekçesi ve dokunulacak alanlar sunulur; açık onay alınmadan kod değiştirilmez.

Onay verilen PR gövdesinde yalnız o onaylı kapsam için şu işaret bulunur:

`LOCKED-CONTRACT-APPROVED: YES`

Bu işaret genel veya kalıcı izin değildir; yalnız ilgili PR kapsamındaki, önceden kullanıcıya sunulmuş değişiklik için geçerlidir.

24 Eylül 2026 itibarıyla ikinci bir kapı daha vardır: kilitli bir dosyayı değiştiren PR, bu koruma kurulumundan sonraki tüm değişikliklerde repo sahibi **muratarslan35** tarafından GitHub review veya PR comment ile ayrıca onaylanmadan CI geçemez. Chat/iş emri onayı önce alınır; bu onay PR'a kayıt olarak yansıtılır.

## Kilitli iş kuralları

1. **Kaynak önceliği:** Resmi sonuçlarda `P2 > P1 > IMS`. Daha düşük öncelikli kaynak daha yüksek öncelikli kaynağı ezemez.
2. **Temsilci 12 aylık grafik:** Ürün/ay bazında yalnız `P2 > P1 > IMS`. `Target.tl_realization` veya başka bir TL fallback yoktur. IMS/üretim olmayan ay için yapay nokta üretilmez. IMS içindeki gerçek sayısal `0` geçerli veridir.
3. **Nisan 2026+ kutu hesabı:** Açık IMS dönemlerinde temsilci, bölge ve Türkiye dahil tüm şirket kutu hedefi ve şirket kutu gerçekleşeni, ilgili resmi TL değeri / o IMS dönemi için geçerli ürün birim fiyatı üzerinden merkezi hesaplanır. Yuvarlama `ROUND_HALF_DOWN`: tam `.50` aşağıda kalır, `.50` üzeri yukarı çıkar. Eski/negatif MF'siz kutu bakiyesi, competition unit veya persisted unit alanı bu sonucu ezemez.
4. **Üretimle kapanan dönem kilidi:** Bir ay için kabul edilmiş P1 veya P2 üretim sonucu oluştuğunda dönem kapanır. O ayın P2/P1 ile kesinleşmiş TL/kutu sonuçları geçmiş ekranlarda yeniden hesaplanmaz; sonraki formül/bug düzeltmeleri yalnız açık mevcut dönem ve ileri dönemlere uygulanır. Kapalı döneme sonradan IMS veya hedef importu yapılamaz.
5. **Aylık birim fiyat kilidi:** Ürün birim fiyatı **aktif IMS ayı** devam ederken değiştirildiğinde yeni fiyat o ayın hiçbir IMS hesabına uygulanmaz; aynı ay daha sonra gelen haftalık IMS dosyaları da ayın kilitli eski fiyatını kullanır. Değişiklik aktif IMS ayını izleyen bir sonraki IMS döneminden itibaren geçerli olur. Aynı aktif ay içinde kaç kez fiyat güncellenirse güncellensin, mevcut ay kendi başlangıç fiyatını korur; yalnız sonraki ay için planlanan fiyat son değerle güncellenir. Geçmiş aylar her zaman kendi dönemsel fiyatını kullanır ve güncel `Product.unit_price` değişikliği geçmiş hedef/kutu/realizasyon sonuçlarını değiştiremez. Fiyat geçişinde duvar saati/takvim ayı değil, merkezi `PeriodService` tarafından belirlenen aktif IMS iş dönemi esas alınır.
6. **TL otoritesi:** Açık IMS döneminde TL hedef ve TL gerçekleşen resmi IMS kaynağından; P1/P2 geldiğinde resmi üretim kaynağından alınır. Kutu/bakiye alanlarından TL türetilmez.
7. **Temsilci rekabet tutarlılığı:** Ürün bazlı rakip toplamı, seçili ürün rakip detayları, toplam kutu pazarı, pazar payı ve aylık rakip değişimi aynı DB veri zincirini kullanır. Önceki ay verisi önceki ayın kendi temsilci-brick kapsamından okunur.
8. **Sayı gösterimi:** Kutu adetlerinde Türkçe binlik ayırıcı `.` kullanılır; ör. `9.360 kutu` = dokuz bin üç yüz altmış. Kutu farkı ve yüzde değişimi ayrı anlamlarla gösterilir.
9. **Bölge/temsilci/Türkiye tutarlılığı:** Aynı iş kuralını kullanan temsilci, bölge ve Türkiye ekranları birbirinden bağımsız alternatif formül üretmez. Bir kaynak/formül değişikliği ilgili tüm tüketici ekranların regresyon testinden geçmeden tamamlanmış sayılmaz.
10. **Özel kimlik kuralları:** `BOS` ve `BOŞ` ayrı kimliklerdir; `BOSTANCI` normal değerdir. Gerçek sayısal `0` boş/verisiz sayılamaz.
11. **Yetki ve güvenlik:** Bölge müdürü kapsamı fail-closed kalır; yetkisiz bölge/temsilci erişimi açılamaz. Admin/özel yetki kuralları mevcut merkezi yetki servisinden okunur.
12. **Dağıtım güvenliği:** İlgili CI PASS olmadan merge yoktur. Production acceptance PASS olmadan tamamlandı denmez. Aktif `PROCESSING` IMS import işi varken deploy/restart yapılmaz. SQLite `WAL` ve `busy_timeout=30000` korunur.
13. **Türkiye Pazar Analizi kaynak ve tekillik kilidi:** `Pazar ve Rakip Analizi` yönetici/temsilci dashboardlarında gösterilmez; yalnız yetkili yöneticilerin `Türkiye Pazar Analizi` ekranında yer alır. Seçili ayın en güncel tamamlanmış IMS haftasında gerçek rekabet TL verisi varsa aynı hafta kullanılır. Güncel haftada rekabet verisi yoksa aynı ay içindeki son kullanılabilir gerçek rekabet haftası kullanılır ve ekranda hem güncel haftanın rekabet verisi taşımadığı hem de kullanılan kaynak hafta açıkça yazılır. Aynı ayda hiç rekabet verisi yoksa ekran tamamen boş dönmez; güncel şirket IMS satışları gösterilir fakat rakip/toplam pazar alanları yapay `0` ile doldurulmaz. Her şirket ürünü tabloda en fazla bir kez yer alır; aynı ürüne ait alias/eski pazar grup satırları toplanarak çift sayım üretmez.
14. **Import otomasyonu kilidi:** Normal hedef akış `upload → preflight/semantic discovery → atomic import/reconciliation → dashboard/region/representative read-model → enrichment → atomic publication` şeklindedir. Bu sıra kullanıcı onayı olmadan değiştirilemez.
15. **Snapshot-only interaktif okuma kilidi:** Dashboard, Türkiye Pazar Analizi, Bölge ve Temsilci interaktif route'ları yayınlanmış read-model/snapshot üzerinden çalışır. Kullanıcı request'i içinde ağır Excel okuma, full aggregation veya alternatif hesap zinciri eklenemez.
16. **Atomik publication kilidi:** Dashboard + region + representative zorunlu generation'ları aynı kabul edilen kaynak için hazır olmadan yeni hafta/tarih görünür olamaz ve progress %100 olamaz. Eksik/başarısız generation durumunda önceki doğrulanmış generation görünür kalır.
17. **Geç production bağımlılık kilidi:** Sonradan gelen P1/P2 ilgili ayın IMS sonucunu değiştirir; üzerine eklenmez. Etkilenen geçmiş ay ve Q/YTD bağımlılıkları durable queue/read-model zinciriyle yenilenir. Historical route dashboard'a kaçamaz.
18. **Ranking kilidi:** Alt IMS Türkiye Sıralaması seçili ayın temsilci ₺ realizasyon sıralamasıdır. Üst Yıllık Ürün Bazlı Türkiye Sıralaması Ocak→seçili ay ürün kutu YTD toplamıdır. Her iki alanda aylık kaynak önceliği P2 > P1 > IMS'tir.
19. **Market payload bütünlüğü kilidi:** Dashboard/ranking refresh tam `competition_analysis` payloadını korumak zorundadır. Rekabet authority mevcutken eksik market read-model yayınlanamaz. Region market/önceki-ay competitor/kutu farkı completeness kontrolleri publication kabulünün parçasıdır.
20. **Kanonik mimari belgesi:** `IMS_IMPORT_READ_ARCHITECTURE_LOCK.md` bu kuralların operasyonel açıklamasıdır ve bu dosyayla birlikte kilitlidir.

## Kilitli kritik kod yolları

Aşağıdaki dosyalarda değişiklik, kullanıcı ön onayı olmadan yapılamaz:

- `app/__init__.py`
- `app/models.py`
- `app/database.py`
- `config.py`
- `.github/CODEOWNERS`
- `app/ims.py`
- `ims_import_worker.py`
- `app/services/ims_import_service.py`
- `app/services/ims_import_queue.py`
- `app/services/ims_publication_service.py`
- `app/services/ims_upload_lifecycle_service.py`
- `app/services/ims_upload_lifecycle_hooks.py`
- `app/services/workbook_preflight.py`
- `app/services/semantic_import_discovery.py`
- `app/services/dynamic_import_contract.py`
- `app/services/dynamic_import_refinement.py`
- `app/services/kpi_workbook_compat.py`
- `app/services/kpi_market_single_source.py`
- `app/services/kpi_market_raw_source_override.py`
- `app/services/kpi_competition_import_source_override.py`
- `app/services/competition_import_service.py`
- `app/services/compiled_competition_import_service.py`
- `app/services/official_aggregate_service.py`
- `app/services/official_brick_spread_service.py`
- `app/services/target_import_service.py`
- `app/services/alias_service.py`
- `app/services/vacancy_matching.py`
- `app/services/dashboard_service.py`
- `app/services/market_analysis_service.py`
- `app/services/persistent_dashboard_snapshot_service.py`
- `app/services/persistent_region_snapshot_service.py`
- `app/services/persistent_representative_snapshot_service.py`
- `app/services/representative_snapshot_refresh_queue.py`
- `app/services/snapshot_generation_identity_guard.py`
- `app/services/historical_region_read_model_service.py`
- `app/services/region_box_authority_guard.py`
- `app/services/period_result_sum_guard.py`
- `app/services/period_service.py`
- `app/services/production_publication_status.py`
- `app/routes/__init__.py`
- `app/regions.py`
- `app/services/production_result_service.py`
- `app/services/tl_box_calculation_service.py`
- `app/services/april_global_box_period_lock.py`
- `app/services/product_unit_price_service.py`
- `app/services/partial_ims_period_price_guard.py`
- `app/services/period_price_read_guard.py`
- `app/services/week8_read_path_repair.py`
- `app/services/region_performance_service.py`
- `app/services/region_performance_bulk_optimizer.py`
- `app/services/representative_period_snapshot_service.py`
- `app/services/annual_realization_service.py`
- `app/services/representative_market_service.py`
- `app/services/region_market_service.py`
- `app/query/dashboard_query.py`
- `app/services/competitive_intelligence_service.py`
- `app/services/actual_sales_resolution_service.py`
- `app/products.py`
- `app/representatives.py`
- `app/region_manager.py`
- `.github/workflows/deploy.yml`
- `.github/workflows/locked-contracts.yml`
- `CANONICAL_LOCKS.md`
- `IMS_IMPORT_READ_ARCHITECTURE_LOCK.md`

## Korunan dosya aileleri

Yukarıdaki tekil dosyalara ek olarak aşağıdaki servis aileleri de kilitlidir. Yeni dosya ekleyerek kanonik akışın etrafından dolaşmak da onay gerektirir:

- `app/services/*import*.py`
- `app/services/*snapshot*.py`
- `app/services/*publication*.py`
- `app/services/*market*.py`
- `app/services/*result*.py`
- `app/services/*authority*.py`
- `app/services/*aggregate*.py`
- `app/services/*read*.py`
- `app/services/*period*.py`
- `app/services/*resolver*.py`
- `app/services/*reconciliation*.py`
- `app/services/*integrity*.py`
- `app/services/*dashboard*.py`
- `app/services/*region_performance*.py`
- `app/services/*brick_spread*.py`
- `app/services/*vacancy*.py`
- `app/services/*kpi*.py`

`CODEOWNERS` bu yollar için `@muratarslan35` sahipliğini ayrıca belirtir. Asıl zorunlu kapı Locked Canonical Contracts workflow'udur; CODEOWNERS inceleme görünürlüğünü güçlendirir.

## Değişiklik protokolü

Kilitli bir alanın değişmesi gerekiyorsa sıralama şöyledir: önce sorun ve önerilen değişiklik kullanıcıya sunulur; etkilenecek dosyalar açıkça belirtilir; Murat Arslan'dan açık onay alınır; yalnız onaylanan dosya/kural değiştirilir; PR gövdesine `LOCKED-CONTRACT-APPROVED: YES` eklenir; repo sahibi onayı review/comment olarak PR'a kaydedilir; bağımlı ekranlar hedefli regresyon testleriyle doğrulanır; tam ilgili CI PASS olur; sonra merge edilir; production acceptance PASS sonrasında tamamlandı denir. Onay kapsamı dışındaki yan değişiklikler aynı PR'a eklenmez.

Bu kilidin amacı geliştirmeyi durdurmak değil, import ve okuma mimarisinin kazara yeniden tasarlanmasını önlemektir. Veri dosyası formatı gerçekten değişirse sistem önce fail-closed davranır; yeni semantic uyarlama ancak yukarıdaki onay protokolüyle yapılır.
