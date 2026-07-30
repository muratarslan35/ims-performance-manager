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

## 2) Yeni Migration Oluşturma

Model değişikliği sonrası:

```bash
python -m flask --app run.py db migrate -m "kısa açıklama"
```

## 3) Migration Çalıştırma

Son sürüme yükseltmek için:

```bash
python -m flask --app run.py db upgrade
```

## 4) Upgrade

Belirli revizyona geçiş:

```bash
python -m flask --app run.py db upgrade <revision_id>
```

## 5) Downgrade

Bir adım geri:

```bash
python -m flask --app run.py db downgrade -1
```

Belirli revizyona geri:

```bash
python -m flask --app run.py db downgrade <revision_id>
```

## 6) Production Deployment Flow

1. Yeni release’i deploy etmeden önce veritabanı yedeği alın.
2. Uygulama kodunu deploy edin.
3. Aynı sürümde migration çalıştırın: `python -m flask --app run.py db upgrade`
4. Uygulama health-check doğrulayın.
5. Gerekirse kontrollü rollback için `db downgrade` planını uygulayın.

Notlar:
- Bu migration seti SQLite ve PostgreSQL ile uyumludur.
- Migration’lar veri kaybını önlemek için yeni nesneleri koşullu/additive şekilde ekler.

## 7) Common Errors & Troubleshooting

### `flask: command not found`
- `python -m flask ...` formatını kullanın.

### `No module named flask`
- `pip install -r requirements.txt` çalıştırın.

### `Target database is not up to date`
- Mevcut revizyonu kontrol edin: `python -m flask --app run.py db current`
- Sonra `db upgrade` çalıştırın.

### `Can't locate revision identified by ...`
- Kod ve migration dosyalarının aynı branch/release sürümünde olduğundan emin olun.

### SQLite / PostgreSQL farkları
- Migration scriptleri dialect kontrolü içerir; SQLite için desteklenmeyen unique-constraint değişimleri unique index ile güvenli şekilde uygulanır.
