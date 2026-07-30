# Database Migrations

Bu proje şema yönetimini tamamen Alembic/Flask-Migrate ile yürütür. Uygulama başlangıcında `db.create_all()` çalışmaz.

## 1) Initial Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Veritabanı bağlantısını ortam değişkeniyle verin:

```bash
export DATABASE_URL="sqlite:///instance/ipm.db"
# veya
export DATABASE_URL="******host:5432/dbname"
```

## 2) Migration Komutları

Yeni migration üretimi:

```bash
python -m flask --app run.py db migrate -m "kısa açıklama"
```

Yükseltme:

```bash
python -m flask --app run.py db upgrade
python -m flask --app run.py db upgrade <revision_id>
```

Düşürme:

```bash
python -m flask --app run.py db downgrade -1
python -m flask --app run.py db downgrade <revision_id>
python -m flask --app run.py db downgrade base
```

Geçerli revizyon kontrolü:

```bash
python -m flask --app run.py db current
```

## 3) Verified Migration Safety Scope

`e7e561790e74_harden_schema_migrations` revizyonunda upgrade adımı additive/non-destructive tasarlanmıştır:
- yeni tablolar eklenir
- yeni index/unique korumaları eklenir
- mevcut IMS tablolara `week_number` kolonu eklenir
- upgrade içinde drop işlemi yoktur

Legacy veri koruma doğrulaması:
- mevcut `users` kayıtları korunur
- mevcut IMS (`ims_uploads`, `ims_raw_data`, `ims_facts`) kayıtları korunur

## 4) SQLite vs PostgreSQL Notes

Fonksiyonel parity hedeflenir (SQL birebirliği değil):
- aynı tablo/kolon seti
- aynı index varlığı
- aynı unique semantiği

Beklenen dialect farkı:
- SQLite'da `uq_ims_fact_week_period` bir **unique index** olarak uygulanır
- PostgreSQL'de aynı kural **unique constraint** olarak uygulanır

## 4.1) Migration Test Split (Default vs PostgreSQL)

Varsayılan migration test akışı SQLite zorunlu doğrulamasını içerir:

```bash
python -m pytest tests/test_database_migrations.py tests/test_config_security.py -v
python -m pytest tests/ -v
```

PostgreSQL parity doğrulaması ayrı bir testte tutulur ve yalnızca PostgreSQL erişilebilir olduğunda çalışır.

PostgreSQL testi için gereksinimler:
- çalışan PostgreSQL instance
- erişilebilir database ve kullanıcı
- `TEST_POSTGRES_URL` ortam değişkeni

Canlı PostgreSQL ile parity çalıştırma komutu:

```bash
TEST_POSTGRES_URL='postgresql+psycopg2://runner@/migration_test?host=/tmp&port=55432' \
python -m pytest tests/test_database_migrations.py -v
```

Beklenen skip davranışı:
- `TEST_POSTGRES_URL` yoksa PostgreSQL parity testi `SKIPPED` olur.
- `TEST_POSTGRES_URL` var ama bağlantı kurulamazsa test, ortam erişilemez mesajıyla `SKIPPED` olur.
- Bu durumlarda test suite başarısız olmaz; SQLite migration doğrulaması yine zorunlu olarak çalışır.

## 5) Downgrade Caveat

Bu revizyonun downgrade adımı bilinçli olarak destrüktiftir:
- migration ile gelen tablolar (`representative_matches`, `product_matches`, `manual_match_queue`, `import_audit_logs`) silinir
- migration ile gelen `week_number` kolonları kaldırılır
- bu kolon/tablolarda oluşan veri geri alınamaz

Downgrade kullanmadan önce mutlaka yedek alın.

## 6) Production Rollout Safety (Single Migrator)

Production ortamında migration tek bir instance tarafından çalıştırılmalıdır:
1. Bakım penceresi açın ve yedek alın.
2. Yeni uygulama sürümünü deploy edin.
3. Sadece **bir** migrator instance ile `db upgrade` çalıştırın.
4. Upgrade tamamlandıktan sonra uygulama instance’larını trafiğe açın.
5. Health-check ve temel smoke testleri doğrulayın.

Uygulama runtime'da schema oluşturmaz. Schema eksikse `initialize_database()` açık log üretir ve production-safe strict modda fail-fast davranır.

## 7) Production Secret Key Safety

Production için `SECRET_KEY` zorunludur:
- `APP_ENV=production` iken `SECRET_KEY` yoksa uygulama başlangıçta fail-fast eder
- test/development ortamlarında geçici dev anahtarı ile çalışma devam eder

## 8) Common Errors & Troubleshooting

### `flask: command not found`
- `python -m flask ...` formatını kullanın.

### `No module named flask`
- `pip install -r requirements.txt` çalıştırın.

### `Target database is not up to date`
- Mevcut revizyonu kontrol edin: `python -m flask --app run.py db current`
- Sonra `db upgrade` çalıştırın.

### `Can't locate revision identified by ...`
- Kod ve migration dosyalarının aynı branch/release sürümünde olduğundan emin olun.
