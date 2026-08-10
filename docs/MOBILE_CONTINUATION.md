# Mobil devam ve üretim senkronizasyonu

Mobil ChatGPT/Codex oturumunda ilk olarak şu dosyaları okuyun:

1. `PROJECT_WORK_PROGRESS.md` — son tamamlanan aşama ve bekleyen işler
2. `PROJECT_AUDIT.md` — mimari, import ve veri denetim bulguları
3. Bu dosya — sunucu ve güvenli otomasyon sözleşmesi

## Üretim hedefi

| Ayar | Değer |
|---|---|
| Sunucu | `130.162.48.162` |
| SSH portu | `22` |
| SSH kullanıcısı | `ubuntu` |
| Uygulama dizini | `/home/ubuntu/ims_system` |
| Uygulama komutu | `venv/bin/python run.py` |
| Uygulama portu | `8000` |

Özel anahtar, parola veya veritabanı Git'e **asla** eklenmez.

## GitHub Actions kurulumu

Repo ayarlarında aşağıdaki GitHub **Variables** değerlerini ekleyin. Workflow varsayılanları aynı değerleri içerir; değişiklik gerektiğinde buradan yönetilebilir.

| Variable | Değer |
|---|---|
| `IMS_SERVER_HOST` | `130.162.48.162` |
| `IMS_SERVER_PORT` | `22` |
| `IMS_SERVER_USER` | `ubuntu` |
| `IMS_DEPLOY_PATH` | `/home/ubuntu/ims_system` |

Ardından GitHub **Actions secret** olarak yalnızca bunu ekleyin:

| Secret | Kaynak |
|---|---|
| `IMS_DEPLOY_SSH_KEY` | Yerel `bist.key` dosyasının tam içeriği |

Bu secret eklendikten sonra `main` dalına yapılan her push, `.github/workflows/deploy.yml` ile sunucuyu fast-forward günceller ve port 8000'deki Flask sürecini yeniden başlatır. İstenen durumda Actions > **Deploy IMS Performance Manager** > **Run workflow** ile mobil tarayıcıdan da elle çalıştırılabilir.

## Mobil oturum için çalışma kuralı

- Önce `PROJECT_WORK_PROGRESS.md` dosyasını okuyun; tamamlanmış dosyaları tekrar denetlemeyin.
- Gerçek IMS veri dosyası gelmeden Nisan/Mayıs/Q kapanış hakkedişi üretmeyin.
- `instance/ipm.db` silinmez veya Git'e eklenmez.
- Yeni kod yalnız hedefli testten sonra küçük, açıklayıcı commit ile `main` dalına gönderilir.
- Son Q/prim ekranı commitleri: `e8f2ae8`, `2caab2f`, `60c5938`.
