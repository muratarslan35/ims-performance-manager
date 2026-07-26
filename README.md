# IMS Performance Manager

Flask tabanlı, ilaç satış temsilcilerinin IMS performansı, hedefleri ve prim hesapları için yönetim uygulaması.

## IMS ETL akışı

IMS Excel içe aktarımı üç kalıcı katmanda çalışır:

| Katman | Tablo | Sorumluluk |
| --- | --- | --- |
| Staging | `IMSRawData` | Excel’deki kaynak satırları, eşleşmemiş temsilciler dahil, denetlenebilir şekilde saklar. |
| Transform | `IMSFact` | Ürün ve temsilci ana verisiyle eşleşen, raporlamaya uygun kayıtları üretir. |
| Aggregate | `IMSSummary` | `year + month + representative + product` düzeyinde dönem toplamlarını oluşturur. |

`IMSImportService` yalnızca bu sırayı kullanır. Bir dönemi yeniden yüklemek varsayılan olarak o dönemin eski raw, fact ve summary kayıtlarını temizler; önceki `IMSUpload` kayıtları ise denetim amacıyla tutulur.

## Kurulum

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

Uygulama varsayılan olarak `instance/ipm.db` SQLite veritabanını kullanır.

## Oracle yapılandırması

Sunucuda bağlantı dizgesini ortam değişkeniyle verin; uygulama bu değer varsa SQLite yerine onu kullanır:

```bash
export DATABASE_URL='oracle+oracledb://user:password@host:1521/?service_name=SERVICE'
```

Oracle Python sürücüsünü sunucunun standartlarına göre kurun. Mevcut bir veritabanında model değişikliklerini `db.create_all()` ile değil Alembic/Flask-Migrate ile yönetin:

```bash
flask --app run.py db migrate -m "add IMS ETL facts"
flask --app run.py db upgrade
```

## Doğrulama

```powershell
python -m unittest tests.test_ims_import_service
python -m compileall -q app config.py run.py tests
```

İlk test, örnek bir Excel sayfasından bir raw kayıt, bir fact ve bir özet kaydı üretildiğini doğrular.
