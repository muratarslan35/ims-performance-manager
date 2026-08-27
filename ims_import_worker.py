"""Single-process worker for persistent IMS import jobs."""
import signal
import time

from app import create_app
from app.extensions import db
from app.services.ims_import_queue import IMSImportQueue


stopping = False


def _stop(*_args):
    global stopping
    stopping = True


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    app = create_app()
    with app.app_context():
        IMSImportQueue.recover_stale()
        while not stopping:
            job = IMSImportQueue.claim_next()
            if job is None:
                db.session.remove()
                time.sleep(2)
                continue
            IMSImportQueue.process(job)
            db.session.remove()


if __name__ == "__main__":
    main()
