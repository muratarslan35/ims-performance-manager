# IMS Performance Manager — 1 Eylül 2026 Workspace Handoff

> Tarih: **1 Eylül 2026 (Europe/Istanbul)**  
> Repo: `muratarslan35/ims-performance-manager`  
> Amaç: Yeni çalışma alanı / PC Codex bu dosyayı okuyarak **buradan devam etsin**.  
> Bu dosya 27 Ağustos tarihli eski handoff kayıtlarının üzerindedir. Eski `PROJECT_WORK_PROGRESS.md` ve `WORKSPACE_HANDOFF_CURRENT.md` tarihsel kayıt olarak kullanılabilir, ancak çelişki halinde bu dosya esas alınmalıdır.

---

## 1. Değiştirilmeyecek ana kurallar

- Mevcut mimari, dashboard hesapları, hedef/prim mantığı ve **P2 > P1 > IMS** önceliği korunacak.
- Full relevant CI yeşil olmadan merge yok.
- Production acceptance PASS olmadan deploy/restart başarılı sayılmayacak.
- IMS import job `PROCESSING` ise deploy/restart yapılmayacak.
- Canlı DB üzerinde benchmark yapılmayacak.
- SQLite `WAL` ve `busy_timeout=30000` korunacak.
- `BOS` ve `BOŞ` ayrı kimliklerdir; `BOSTANCI` normal değerdir.
- Numeric `0` gerçek veridir, blank sayılmaz.
- İstenen alan dışında UI/formül/ayar değiştirilmeyecek.
- Fail-closed importer/validation gevşetilmeyecek.
- Diagnostic branch'ler **NEVER MERGE**.

---

## 2. Güncel main

1 Eylül 2026 itibarıyla görülen main SHA:

`cb0b06e9177ce8a4cab7c2dba45bddabf1fd3966`

Bu commit PR **#385** merge sonucudur:

**Add region-scoped manager administration and access control**

Commit mesajındaki kapsam:

- regional manager access scope ve management module,
- regional manager administration UI,
- navigation scope,
- regional manager scope table,
- Murat Asan unrestricted manager access korunması,
- representative selector scope,
- regional exemption ile dual portal access'in ayrılması,
- fail-closed access scope testleri.

**Önemli:** Kullanıcı canlıda modülün görünür olduğunu kontrol etti. Ancak bu mobil oturum, PR #385 sonrasında production'daki tüm arka plan yetki/migration/access kurallarını yeniden acceptance ile doğrulamadan burada durdu. Yeni çalışma alanı ilk iş olarak canlı production acceptance yapmalı; modülün tam doğru çalıştığını varsaymamalı.

---

## 3. Week14 / Mart IMS durumu

Upload #29 = Mart 2026, Week14.

Week14 compact TTS gerçek temsilci actual authority düzeltmesi tamamlandı:

- PR #374 merge edildi.
- Compact `TTS ÇIKIŞLARI` 3-block layout'ta direct representative+product cumulative TL actual authoritative.
- `1001 BRICK SATIS` yalnız brick analysis authority olarak kalır.
- Numeric zero authoritative, blank unavailable.
- NATIONAL/region subtotal representative summary'ye girmez.
- Brick `IMSFact` satırları değişmez.

Production deploy gate'teki stale post-import official side-channel audit sorunu PR #376 ile çözüldü; live gate tekrar PASS oldu.

Week14 post-repair acceptance ayrıca PASS verdi:

- 113 temsilci,
- 791 representative×product,
- Gülbahar Kara ve Yasin Tını dahil compact TTS direct actual'lar workbook ile eşleşti,
- IMS fact/raw/competition/official aggregate invariantları korundu.

---

## 4. Hedef Yönetimi düzeltmesi

Eski Hedef Yönetimi ekranı Jan+Feb+Mar target satırlarını tek temsilci altında karıştırdığı için:

- Toplam Hedef = 2373,
- her temsilci = 21 ürün,
- dönem kartı = 1

gösteriyordu.

PR #378 ile latest target period scope uygulandı.

Production acceptance sonucu:

- Aktif Hedef Dönemi: **03/2026**
- Toplam Hedef: **791**
- Aktif Temsilci: **113**
- Aktif Ürün: **7**
- 113 temsilcinin her birinde **7** current-period target
- Jan 791 + Feb 791 + Mar 791 historical DB satırları korunuyor; toplam DB target = 2373
- yeni target formu Mart'a default oluyor
- eski “21 ürün” current management render'ında yok.

Target/prim/IMS formülleri değiştirilmedi.

---

## 5. Mart 2. üretim P2 — final durum

Mart 2. üretim dosyası ilk başta fail-closed oldu.

Kök neden:

- KUTU sheet'inde eski/pasif `İLAYDA NUR VARSAK` satırı vardı,
- TL tarafında güncel `501 Ankara / ANKARA BOS KADRO` vardı,
- iki sheet roster'ı birebir eşleşmiyordu.

İlk düzeltme eski 0-actual roster satırlarını güvenli ele aldı; sonraki audit, bunun basitçe atılacak satır değil boşalan kadronun eski isimli KUTU tarafı olduğunu gösterdi.

Kanıtlı vacancy continuity kuralı geliştirildi:

- aynı bölge,
- TL'de eksik vacancy,
- KUTU'da pasif eski gerçek kişi,
- actual = 0,
- ürün seti aynı,
- workbook içi hedef fiyat dönüşümü birebir,
- tekil aday,
- ambiguity/non-zero/TL divergence => fail-closed.

PR #382 production'a çıktı.

Read-only parse acceptance:

- 113 temsilci/kadro,
- 791 representative×product,
- 11 bölge,
- 77 region×product,
- Ankara BOS KADRO = 7 ürün,
- Ilayda final production scope = 0 kayıt.

Safe apply sonrası bağımsız read-only production acceptance **PASS**:

- Production upload #3 = `APPLIED`
- Final production stage = 2
- representative×product = 791
- representative totals = 113
- national products = 7
- national total = 1
- region×product = 77
- region totals = 11
- Ankara BOS KADRO (#112) = 7 ürün
- Ilayda (#115) = 0 production result
- active/queued IMS job = 0
- March Target = 791
- Week14 IMS facts = 791
- Week14 IMS summary = 791
- latest IMS upload #29 / 14. hafta korunuyor
- SQLite WAL + busy_timeout=30000 korunuyor.

Sonuç: Mart 2. üretim **P2 aktif** ve P2 > P1 > IMS önceliğinde kullanılabilir.

---

## 6. Backup temizliği

Mart P2 uygulama öncesi alınan önemli canlı backup:

`pre_march_stage2_apply_20260901_082416.sqlite`

Bu backup yaklaşık 2.13 GB ve korunacak rollback noktası olarak işaretlendi.

Backup cleanup workflow'da eski/tekrarlı yedeklerin silinmesi planlandı; korunacak set içinde en az:

- `pre_week14_compact_tts_actual_repair_20260831_212357.sqlite`
- `pre_march_stage2_apply_20260901_082416.sqlite`

vardı.

Yeni çalışma alanı disk temizliğiyle devam edecekse önce canlı backup dizinini yeniden inventory etsin; eski statik envantere güvenerek dosya silmesin. Çalışan DB, IMS archive/source dosyaları ve yukarıdaki rollback backup'ları korunmalı.

---

## 7. Normal şirket yöneticisi / Manager hesabı

Kullanıcı açıkça ayırdı:

Bu yöneticiler sistem `Admin` hesabı değildir. Şirketteki bölge müdürü/yönetici kullanıcılarıdır.

Yanlış kapsamlı PR #384 (`persistent admin bootstrap`) **kapatıldı ve merge edilmedi**.

Normal Manager kullanıcı olarak canlı DB'ye eklenen hesap:

- Ad: **Mehmet Özkoçak**
- E-posta: `mehmet.ozkocak@bilimilac.com`
- Rol: `Manager`
- Active: True
- Live user id: 4

Parola bu handoff dosyasına **bilinçli olarak yazılmamıştır**.

Bağımsız read-only production verification:

- user exists = 1
- role = Manager
- active = True
- `is_manager(user)` = True
- duplicate email count = 1
- mevcut `admin@ipm.local` Admin hesabı korunmuş
- IMS job active = 0
- SQLite WAL + busy_timeout=30000
- `MANAGER_USER_VERIFY|PASS`

---

## 8. Bölge Müdürü Yönetim Modülü — kullanıcı isteği

Admin/Murat Arslan tarafına yönetici modülü isteniyor.

Yeni bölge müdürü ekleme formunda:

- İsim Soyisim
- Mail
- Şifre
- Bölge

alanları olacak.

Bölge kodları sistemdeki mevcut kod yapısıyla sınırlandırılabilir: ör. `101`, `201`, `301` ...; **hard-code edilmek yerine mümkünse canlı master bölge listesinden doğrulanmalı**.

### Bölge müdürü yetkileri

Bölge müdürü:

- sisteme kendi mail/şifresiyle Manager portalından girer,
- ana dashboard'ın Türkiye/genel KPI verilerini okuyabilir,
- ancak başka bölgenin detayına giremez,
- yalnız kendi bölgesinin bölge detayını açabilir,
- yalnız kendi bölgesindeki temsilcilerin detaylarını açabilir,
- arama sonuçlarında yalnız kendi bölgesinin temsilci/bölge detaylarına erişebilir,
- başka bölgeye doğrudan URL ile girerse de fail-closed engellenir,
- mesaj: **“Bu bölgenin yöneticisi değilsiniz.”**
- IMS upload yapamaz,
- sistem ayarlarını değiştiremez,
- kullanıcı/master/territory gibi yönetimsel mutation ekranlarına erişemez,
- Prim Simülasyonu yalnız kendi bölgesinin çalışanlarını görür,
- Q verileri yalnız kendi bölgesinin çalışanlarını görür,
- başka bölge üzerinde müdahale/değişiklik yapamaz.

### İstisna

Sistemde kayıtlı `murat.asan@bilimilac.com` yöneticisinin daha önce belirlenmiş özel/unrestricted yetkileri **korunacak**; yeni regional-manager kısıtlarına yanlışlıkla dahil edilmeyecek.

### Güvenlik prensibi

UI'da link gizlemek tek başına yeterli değildir. Yetki kontrolü route/service/query seviyesinde merkezi olmalı. Search/autocomplete, representative detail, region detail, prime simulation, Q API/endpoints ve doğrudan URL girişleri aynı regional scope sözleşmesini kullanmalı.

---

## 9. PR #385 — kod tarafındaki son durum

Main commit `cb0b06e...` mesajına göre PR #385 şu parçaları ekledi:

- region-scoped manager administration and access control,
- regional manager administration UI,
- regional manager navigation scope,
- regional manager scope table,
- Murat Asan unrestricted access exemption,
- representative selector scope,
- regional detail selector scope,
- regional manager fail-closed tests,
- regional exemption ile dual portal access ayrımı.

Kullanıcı canlı UI'da bu modülün **canlıya alınmış göründüğünü** kontrol etti.

### Fakat burada bırakılan kritik iş

Bu oturum PR #385 için canlı production acceptance'ı tamamlamadan durdu. Yeni çalışma alanı **önce doğrulama yapmalı**.

Kontrol edilmesi gerekenler:

1. Production HEAD gerçekten `cb0b06e9177ce8a4cab7c2dba45bddabf1fd3966` veya daha yeni mi?
2. Migration/current schema regional manager scope tablosunu içeriyor mu?
3. Existing Mehmet Manager kaydı scope tablosunda nasıl temsil ediliyor? Bölgesi atanmış mı, yoksa henüz unrestricted legacy Manager mı?
4. Yeni yönetici formu yalnız yetkili Admin/Murat hesabında görünür mü?
5. Bölge müdürü IMS upload/settings/master mutation endpointlerine GET/POST ile erişemiyor mu?
6. Dashboard genel KPI'ları görülebiliyor mu?
7. Kendi region detail = PASS; başka region detail = “Bu bölgenin yöneticisi değilsiniz.”
8. Kendi representative detail = PASS; başka region representative = blocked.
9. Search/autocomplete başka bölge temsilcilerini detail erişimine açmıyor mu?
10. Prime Simulation yalnız assigned region çalışanlarını getiriyor mu?
11. Q data/API yalnız assigned region çalışanlarını getiriyor mu?
12. Direct URL bypass yok mu?
13. `murat.asan@bilimilac.com` eski unrestricted yetkilerini aynen koruyor mu?
14. `admin@ipm.local` ve Murat Arslan admin/master yönetim erişimleri etkilenmemiş mi?
15. WAL/busy_timeout ve IMS job gate korunuyor mu?

Bu maddeler production acceptance ile PASS olmadan regional manager modülü “tamamlandı” kabul edilmemeli.

---

## 10. Yeni çalışma alanına verilecek başlangıç promptu

Yeni çalışma alanında şunu kullan:

> GitHub repo `muratarslan35/ims-performance-manager`. Önce `WORKSPACE_HANDOFF_2026-09-01.md` dosyasını oku ve oradaki kanonik kurallara göre devam et. Güncel main PR #385 ile regional manager scope modülünü içeriyor. Kod yazmadan önce production'da modülün migration + yetki + route/query scope acceptance'ını yap. Özellikle Manager kullanıcıların başka bölge detaylarına, temsilcilerine, IMS upload/settings'e, prime simulation ve Q verilerine erişemediğini; kendi bölgelerinde erişebildiğini ve `murat.asan@bilimilac.com` unrestricted istisnasının korunduğunu doğrula. IMS import PROCESSING ise deploy/restart yapma. Full relevant CI ve production acceptance PASS olmadan tamamlandı deme. Mevcut P2 > P1 > IMS, hedef/prim/dashboard, BOS/BOŞ ve SQLite WAL/busy_timeout kurallarını değiştirme.

---

## 11. Şu anda yapılmaması gerekenler

- PR #385 production acceptance yapılmadan yetki sistemini yeniden tasarlama.
- Mehmet hesabını sistem Admin'e dönüştürme.
- Regional Manager'lara IMS upload veya settings izni verme.
- `murat.asan@bilimilac.com` unrestricted istisnasını kaldırma.
- Başka bölge verilerini yalnız frontend filtrelemesiyle gizleyip backend'i açık bırakma.
- Live DB benchmark yapma.
- IMS job PROCESSING iken restart/deploy yapma.
- Eski Week14/P2 düzeltmelerini yeniden açma; yeni kanıt olmadan veri repair yapma.

---

## 12. Özet

- Week14 IMS repair: **PASS**.
- Hedef Yönetimi latest-period scope: **PASS**.
- Mart 2. üretim P2 apply: **PASS**.
- Mehmet Özkoçak normal Manager account: **PASS**.
- Yanlış Admin bootstrap PR #384: **CLOSED / NOT MERGED**.
- Regional Manager module PR #385: **MERGED TO MAIN; kullanıcı canlıda görünür olduğunu gördü**.
- Regional Manager production backend/migration/access acceptance: **BU HANDOFF'TA HENÜZ TAM DOĞRULANMADI — SIRADAKİ ANA GÖREV**.
