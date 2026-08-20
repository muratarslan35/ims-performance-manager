"""Additional non-layout-specific checks for the isolated IMS acceptance database."""
from __future__ import annotations

import json
import os
from pathlib import Path

from app import create_app
from app.models import IMSUpload, Representative
from app.services.import_result_report import latest_import_report
from app.services.vacancy_matching import canonical_vacancy_text, vacancy_slot_token, vacancy_stable_suffix
from config import Config


class AcceptanceConfig(Config):
    TESTING = True
    USER_VAULT_PATH = Path("/tmp/ims-acceptance-users-disabled.db")


def _assert_isolated_db():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("Acceptance extras yalnız izole SQLite DB üzerinde çalışır.")
    path = Path(database_url.removeprefix("sqlite:///"))
    if not path.name.startswith("ims-acceptance-"):
        raise RuntimeError(f"Canlı DB üzerinde acceptance extras engellendi: {path}")


def _vacancy_context(value):
    canonical = canonical_vacancy_text(value)
    ignored = {"BOS", "BOŞ", "KADRO", "BRICK", "ATANMAMIŞ"}
    tokens = [token for token in canonical.split() if token not in ignored]
    # Keep context order but remove repeated tokens so legacy/new display-label
    # differences do not hide that BOS and BOŞ belong to the same slot context.
    unique = []
    for token in tokens:
        if token not in unique:
            unique.append(token)
    return " ".join(unique)


def _vacancy_identity_check():
    # Stable cadre identity lives in Representative, not only in the current
    # upload's FACT set. This proves the persisted registry keeps BOS and BOŞ
    # separate even when one slot has zero sales in a particular IMS period.
    representatives = Representative.query.all()
    slots = {}
    for representative in representatives:
        labels = [representative.rep_name, representative.territory, representative.city]
        for label in labels:
            token = vacancy_slot_token(label)
            if token not in {"BOS", "BOŞ", "BOS_KADRO", "BOŞ_KADRO"}:
                continue
            context = _vacancy_context(label)
            if not context:
                continue
            slots.setdefault(context, {}).setdefault(token, set()).add(representative.id)

    verified_pairs = []
    for context, tokens in slots.items():
        bos_ids = set(tokens.get("BOS", set())) | set(tokens.get("BOS_KADRO", set()))
        bos_cedilla_ids = set(tokens.get("BOŞ", set())) | set(tokens.get("BOŞ_KADRO", set()))
        if bos_ids and bos_cedilla_ids:
            if bos_ids & bos_cedilla_ids:
                raise AssertionError(
                    f"BOS/BOŞ aynı Representative ID'ye çöktü: context={context}, ids={sorted(bos_ids & bos_cedilla_ids)}"
                )
            verified_pairs.append({
                "context": context,
                "bos_ids": sorted(bos_ids),
                "bos_cedilla_ids": sorted(bos_cedilla_ids),
            })

    bad_normal_names = []
    for representative in representatives:
        for label in (representative.rep_name, representative.territory, representative.city):
            canonical = canonical_vacancy_text(label)
            if "BOSTANCI" in canonical and vacancy_slot_token(label) is not None:
                bad_normal_names.append({"id": representative.id, "label": label})
    if bad_normal_names:
        raise AssertionError(f"BOSTANCI vacancy olarak yorumlandı: {bad_normal_names}")
    # A production period does not have to contain both spellings in the same
    # location. Prove the canonical ID contract directly even when no natural
    # pair exists; never create synthetic production representatives merely to
    # satisfy acceptance evidence.
    if vacancy_stable_suffix("DİYARBAKIR BOS") == vacancy_stable_suffix("DİYARBAKIR BOŞ"):
        raise AssertionError("BOS/BOŞ canonical stable ID sözleşmesi çöktü.")
    return verified_pairs


def main():
    _assert_isolated_db()
    app = create_app(AcceptanceConfig)
    with app.app_context():
        current = (
            IMSUpload.query.filter_by(status="COMPLETED")
            .order_by(IMSUpload.completed_at.desc(), IMSUpload.id.desc())
            .first()
        )
        if current is None:
            raise RuntimeError("Acceptance COMPLETED upload bulunamadı.")

        report = latest_import_report(upload_id=current.id)
        if not report or report.get("upload_id") != current.id:
            raise AssertionError(
                f"Yönetici import raporu son acceptance uploadına ait değil: upload={current.id}, report={report and report.get('upload_id')}"
            )
        if report.get("final_result") != "PASS":
            raise AssertionError(f"Yönetici import raporu PASS değil: {report}")
        critical = report.get("critical") or {}
        if any(int(value or 0) for value in critical.values()):
            raise AssertionError(f"Yönetici raporunda blocking sayaç var: {critical}")
        sheets = report.get("sheets") or {}
        if int(sheets.get("verified", 0)) != int(sheets.get("total", 0)):
            raise AssertionError(f"Manifest tam değil: {sheets}")
        national = report.get("national_region")
        if national and (not national.get("passed") or national.get("conflicts")):
            raise AssertionError(f"NATIONAL/region reconciliation PASS değil: {national}")

        vacancy_pairs = _vacancy_identity_check()
        payload = {
            "result": "PASS",
            "upload_id": current.id,
            "file_name": current.file_name,
            "manager_report": {
                "final_result": report.get("final_result"),
                "sheets": sheets,
                "source": report.get("source"),
                "counts": report.get("counts"),
                "critical": critical,
                "national_region": national,
                "previous_ims_delta": report.get("previous_ims_delta"),
            },
            "bos_bos_cedilla_pairs": vacancy_pairs,
            "bos_bos_cedilla_pair_count": len(vacancy_pairs),
        }
        print("IMS_ACCEPTANCE_EXTRA|" + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        return 0


if __name__ == "__main__":
    main()
