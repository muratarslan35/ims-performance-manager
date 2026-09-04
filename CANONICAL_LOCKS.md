# IMS Performance Manager — Kanonik Değişim Kilidi

Durum: **KİLİTLİ**
Başlangıç referansı: `24416e4503412f033a35806d8b40f42ecea8ccbe` (PR #450 sonrası main)

Bu dosyada listelenen kurallar ve bunları uygulayan kritik kod yolları artık varsayılan olarak değiştirilemez. Bir görev bu alanlardan herhangi birini değiştirmeyi gerektiriyorsa değişiklik yapılmadan önce kullanıcıya etkisi, gerekçesi ve dokunulacak alanlar sunulur; açık onay alınmadan kod değiştirilmez.

Onay verilen PR gövdesinde yalnız o onaylı kapsam için şu işaret bulunur:

`LOCKED-CONTRACT-APPROVED: YES`

Bu işaret genel veya kalıcı izin değildir; yalnız ilgili PR kapsamındaki, önceden kullanıcıya sunulmuş değişiklik için geçerlidir.

## Kilitli iş kuralları

1. **Kaynak önceliği:** Resmi sonuçlarda `P2 > P1 > IMS`. Daha düşük öncelikli kaynak daha yüksek öncelikli kaynağı ezemez.
2. **Temsilci 12 aylık grafik:** Ürün/ay bazında yalnız `P2 > P1 > IMS`. `Target.tl_realization` veya başka bir TL fallback yoktur. IMS/üretim olmayan ay için yapay nokta üretilmez. IMS içindeki gerçek sayısal `0` geçerli veridir.
3. **Nisan 2026+ kutu hesabı:** Açık IMS dönemlerinde temsilci, bölge ve Türkiye dahil tüm şirket kutu hedefi ve şirket kutu gerçekleşeni, ilgili resmi TL değeri / o IMS dönemi için geçerli ürün birim fiyatı üzerinden merkezi hesaplanır. Yuvarlama `ROUND_HALF_DOWN`: tam `.50` aşağıda kalır, `.50` üzeri yukarı çıkar. Eski/negatif MF'siz kutu bakiyesi, competition unit veya persisted unit alanı bu sonucu ezemez.
4. **Üretimle kapanan dönem kilidi:** Bir ay için kabul edilmiş P1 veya P2 üretim sonucu oluştuğunda dönem kapanır. O ayın P2/P1 ile kesinleşmiş TL/kutu sonuçları geçmiş ekranlarda yeniden hesaplanmaz; sonraki formül/bug düzeltmeleri yalnız açık mevcut dönem ve ileri dönemlere uygulanır. Kapalı döneme sonradan IMS veya hedef importu yapılamaz.
5. **Aylık birim fiyat kilidi:** Ürün birim fiyatı ay içinde değiştirildiğinde yeni fiyat aynı ayın hiçbir IMS hesabına uygulanmaz. Değişiklik bir sonraki takvim ayının IMS döneminden itibaren geçerli olur. Aynı ay içinde kaç kez fiyat güncellenirse güncellensin, mevcut ay kendi başlangıç fiyatını korur; yalnız sonraki ay için planlanan fiyat son değerle güncellenir. Geçmiş aylar her zaman kendi dönemsel fiyatını kullanır ve güncel `Product.unit_price` değişikliği geçmiş hedef/kutu/realizasyon sonuçlarını değiştiremez.
6. **TL otoritesi:** Açık IMS döneminde TL hedef ve TL gerçekleşen resmi IMS kaynağından; P1/P2 geldiğinde resmi üretim kaynağından alınır. Kutu/bakiye alanlarından TL türetilmez.
7. **Temsilci rekabet tutarlılığı:** Ürün bazlı rakip toplamı, seçili ürün rakip detayları, toplam kutu pazarı, pazar payı ve aylık rakip değişimi aynı DB veri zincirini kullanır. Önceki ay verisi önceki ayın kendi temsilci-brick kapsamından okunur.
8. **Sayı gösterimi:** Kutu adetlerinde Türkçe binlik ayırıcı `.` kullanılır; ör. `9.360 kutu` = dokuz bin üç yüz altmış. Kutu farkı ve yüzde değişimi ayrı anlamlarla gösterilir.
9. **Bölge/temsilci/Türkiye tutarlılığı:** Aynı iş kuralını kullanan temsilci, bölge ve Türkiye ekranları birbirinden bağımsız alternatif formül üretmez. Bir kaynak/formül değişikliği ilgili tüm tüketici ekranların regresyon testinden geçmeden tamamlanmış sayılmaz.
10. **Özel kimlik kuralları:** `BOS` ve `BOŞ` ayrı kimliklerdir; `BOSTANCI` normal değerdir. Gerçek sayısal `0` boş/verisiz sayılamaz.
11. **Yetki ve güvenlik:** Bölge müdürü kapsamı fail-closed kalır; yetkisiz bölge/temsilci erişimi açılamaz. Admin/özel yetki kuralları mevcut merkezi yetki servisinden okunur.
12. **Dağıtım güvenliği:** İlgili CI PASS olmadan merge yoktur. Production acceptance PASS olmadan tamamlandı denmez. Aktif `PROCESSING` IMS import işi varken deploy/restart yapılmaz. SQLite `WAL` ve `busy_timeout=30000` korunur.

## Kilitli kritik kod yolları

Aşağıdaki dosyalarda değişiklik, kullanıcı ön onayı olmadan yapılamaz:

- `app/services/production_result_service.py`
- `app/services/tl_box_calculation_service.py`
- `app/services/april_global_box_period_lock.py`
- `app/services/product_unit_price_service.py`
- `app/services/period_price_read_guard.py`
- `app/services/week8_read_path_repair.py`
- `app/services/region_performance_service.py`
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

## Değişiklik protokolü

Kilitli bir alanın değişmesi gerekiyorsa sıralama şöyledir: önce sorun ve önerilen değişiklik kullanıcıya sunulur; onay alınır; yalnız onaylanan dosya/kural değiştirilir; bağımlı ekranlar hedefli regresyon testleriyle doğrulanır; tam ilgili CI PASS olur; sonra merge edilir; production acceptance PASS sonrasında tamamlandı denir. Onay kapsamı dışındaki yan değişiklikler aynı PR'a eklenmez.
