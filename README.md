# IMS Performance Manager

Flask tabanlı IMS performans yönetimi uygulaması.

## Temel veritabanı ilkeleri

- Şema yönetimi yalnızca Alembic/Flask-Migrate ile yapılır.
- Uygulama başlangıcında `db.create_all()` çalıştırılmaz.
- Varsayılan çalışma veritabanı: `instance/ipm.db`
- Migration zinciri baştan sona uygulanarak sıfırdan kurulabilir.

## Clean install / deployment flow (Oracle VM dahil)

```bash
git clone https://github.com/muratarslan35/ims-performance-manager.git
cd ims-performance-manager
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m flask --app run.py db upgrade
python verify_runtime.py
python -m flask --app run.py run
```

Bu akış sonunda uygulama IMS yüklemesi için hazırdır.

## Migration flow

```bash
python -m flask --app run.py db history
python -m flask --app run.py db heads
python -m flask --app run.py db current
python -m flask --app run.py db upgrade
```

## Runtime verification

`verify_runtime.py` aşağıdakileri kontrol eder:

- git branch + commit
- çalışma dizini
- Python sürümü
- Flask app yüklenmesi
- SQLAlchemy URI
- Alembic current/head revizyonu
- DB dosya yolu
- şema drift (model vs DB)
- zorunlu kolon varlığı
- clean-state satır sayımı (core IMS tabloları)
- import pipeline readiness

Çalıştırma:

```bash
python verify_runtime.py
```

Tüm kontroller geçerse exit code `0`, aksi durumda non-zero döner.

## Seed / bootstrap (yalnızca sistem verileri)

`bootstrap_system_data.py` migration + deterministic sistem seed uygular:

- varsayılan admin kullanıcı
- uygulama ayarları
- sabit ürün tanımları
- gerekli prime rule kayıtları

Yüklemez:

- `ims_uploads`
- `ims_raw_data`
- `ims_facts`
- `ims_summary`
- temsilci iş verileri / geçmiş import kayıtları

Çalıştırma:

```bash
python bootstrap_system_data.py
```

## DB reset (güvenli yaklaşım)

Sadece temiz ortam yeniden kurulumunda:

1. uygulamayı durdurun
2. `instance/ipm.db` dosyasını kaldırın (veya farklı bir `DATABASE_URL` kullanın)
3. `python -m flask --app run.py db upgrade`
4. `python bootstrap_system_data.py`
5. `python verify_runtime.py`

Not: canlı ortamda veri koruma gereksinimi varsa manuel dosya silme yerine yedek/restore prosedürü uygulayın.

## IMS upload

1. uygulamayı başlatın
2. admin hesabıyla giriş yapın (`admin@ipm.local`)
3. IMS ekranından Excel dosyasını seçin
4. yıl/ay girip yüklemeyi başlatın
5. upload tamamlandıktan sonra dashboard/rapor kontrollerini yapın

## Schema drift troubleshooting

Belirtiler:

- `no such column`
- `has no column named`
- import sırasında `OperationalError`

Adımlar:

1. `python -m flask --app run.py db current`
2. `python -m flask --app run.py db heads`
3. current != head ise `python -m flask --app run.py db upgrade`
4. `python verify_runtime.py` çalıştırın

## Test

```bash
python -m pytest tests/ -v
```
