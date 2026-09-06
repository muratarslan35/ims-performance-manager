from pathlib import Path

from flask import Flask

from app.services.ims_progress_store import IMSProgressStore


def test_progress_store_persists_and_clamps(tmp_path):
    app = Flask(__name__, instance_path=str(tmp_path / "instance"))
    with app.app_context():
        written = IMSProgressStore.write(
            42,
            percent=137,
            stage="competition",
            message="Rekabet verileri okunuyor",
            detail="2/3 rekabet sayfası",
        )
        assert written["percent"] == 100
        stored = IMSProgressStore.read(42)
        assert stored["job_id"] == 42
        assert stored["percent"] == 100
        assert stored["message"] == "Rekabet verileri okunuyor"
        assert (Path(app.instance_path) / "ims_progress" / "job-42.json").is_file()


def test_progress_ui_is_server_driven_not_random():
    source = Path("app/static/js/layout.js").read_text(encoding="utf-8")
    assert "fetch('/ims/progress'" in source
    assert "imsRealProgressPercent" in source
    assert "Math.random" not in source


def test_worker_progress_messages_are_turkish_and_user_facing():
    queue = Path("app/services/ims_import_queue.py").read_text(encoding="utf-8")
    worker = Path("ims_import_worker.py").read_text(encoding="utf-8")
    expected_queue = (
        "Dosya kontrol ediliyor",
        "Sayfalar okunuyor",
        "Temsilciler ve bölgeler eşleştiriliyor",
        "Hedefler okunuyor",
        "Ürün çıkışları okunuyor",
        "Rekabet verileri okunuyor",
        "Veriler karşılaştırılıyor ve doğrulanıyor",
        "Son kayıtlar tamamlanıyor",
        "Veriler ekrana aktarılıyor",
    )
    for message in expected_queue:
        assert message in queue
    assert "IMS yüklemesi ve analiz ekranları hazır" in worker


def test_progress_channel_does_not_commit_main_import_transaction():
    source = Path("app/services/ims_progress_store.py").read_text(encoding="utf-8")
    assert "db.session" not in source
    assert "os.replace" in source
