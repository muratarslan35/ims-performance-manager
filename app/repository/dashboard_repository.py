"""
V3 Mimarisi: Dashboard Repository Katmanı
=========================================
Dashboard için sadece salt okunur (Read-Only) veri erişim katmanı.
Basit CRUD okuma işlemleri, tekli/çoklu kayıt çekme ve sayaç (count) işlemlerini barındırır.
Kesinlikle iş kuralları (business logic), agregasyon (GROUP BY, SUM, AVG), 
DTO (Data Transfer Object) dönüşümleri, Dict eşlemeleri (mapping) veya DML (INSERT, UPDATE, DELETE) işlemleri İÇERMEZ.
Diğer motorlar (Prime, Quarter, AI vb.) tarafından da kullanılabilecek 
kurumsal (enterprise) seviyede tasarlanmıştır. Saf veritabanı okuma (Pure Read Repository) katmanıdır.
"""

from dataclasses import dataclass
from typing import List, Optional, Any, Sequence
from sqlalchemy import desc
from sqlalchemy.engine.row import Row

from app.extensions import db
from app.models import (
    Product, 
    Representative, 
    Target, 
    IMSUpload, 
    IMSSummary,
    Setting,
    RepresentativeBrickAssignment,
)

# V3 mimarisinde opsiyonel olabilecek tablolar için güvenli içe aktarma
try:
    from app.models import ImportAuditLog, RepresentativeMatch, ProductMatch, ManualMatchQueue
except ImportError:
    ImportAuditLog = RepresentativeMatch = ProductMatch = ManualMatchQueue = None


@dataclass
class SystemCounts:
    """Veritabanından okunan ham sayaç verilerini tutan tip güvenli veri sınıfı."""
    total_products: int
    total_representatives: int
    total_targets: int
    total_uploads: int
    completed_uploads: int
    failed_uploads: int
    processing_uploads: int


class DashboardRepository:
    """
    Sadece veritabanından ORM modellerini okumaktan sorumlu Repository sınıfı.
    Query Layer'daki analitik karmaşıklıklardan (OLAP) tamamen izole edilmiştir.
    Hiçbir metodu başka bir metodunu çağırıp sarmalayamaz (no wrappers).
    """

    def __init__(self, session=None):
        """Repository katmanını başlatır. Dependency Injection (DI) destekler."""
        self.session = session or db.session

    def load_counts(self) -> SystemCounts:
        """
        Sistemdeki ana varlıkların (entity) toplam sayılarını döndürür.
        Sadece basit .count() fonksiyonlarını kullanır ve tip güvenli veri sınıfı döner.
        """
        return SystemCounts(
            total_products=self.session.query(Product).filter_by(is_active=True).count(),
            total_representatives=self.session.query(Representative).filter_by(active=True).count(),
            total_targets=self.session.query(Target).count(),
            total_uploads=self.session.query(IMSUpload).count(),
            completed_uploads=self.session.query(IMSUpload).filter_by(status="COMPLETED").count(),
            failed_uploads=self.session.query(IMSUpload).filter_by(status="FAILED").count(),
            processing_uploads=self.session.query(IMSUpload).filter_by(status="PROCESSING").count()
        )

    def load_last_upload(self) -> Optional[IMSUpload]:
        """Sisteme yüklenen son IMS Upload kaydını ham ORM objesi olarak döndürür."""
        return self.session.query(IMSUpload).order_by(desc(IMSUpload.uploaded_at)).first()

    def load_recent_uploads(self, limit: int = 5) -> List[IMSUpload]:
        """Sisteme yüklenen son N adet IMS Upload kaydını döndürür."""
        return self.session.query(IMSUpload).order_by(desc(IMSUpload.uploaded_at)).limit(limit).all()

    def load_brick_assignments(self, year: int, month: int) -> List[Any]:
        return self.session.query(RepresentativeBrickAssignment).filter_by(
            year=year, month=month, active=True
        ).all()

    def load_upload(self, upload_id: int) -> Optional[IMSUpload]:
        """Belirtilen ID'ye sahip upload kaydını getirir."""
        return self.session.query(IMSUpload).filter_by(id=upload_id).first()

    def load_upload_by_checksum(self, checksum: str) -> Optional[IMSUpload]:
        """Benzersiz dosya özeti (checksum) ile upload kaydını arar."""
        return self.session.query(IMSUpload).filter_by(checksum=checksum).first()

    def load_upload_by_version(self, version: str) -> List[IMSUpload]:
        """Belirtilen import versiyonu ile işlenmiş yüklemeleri getirir."""
        return self.session.query(IMSUpload).filter_by(import_version=version).all()

    def load_latest_completed_upload(self) -> Optional[IMSUpload]:
        """Başarıyla tamamlanmış (COMPLETED) son upload kaydını getirir."""
        return (
            self.session.query(IMSUpload)
            .filter_by(status="COMPLETED")
            .order_by(desc(IMSUpload.completed_at))
            .first()
        )

    def load_latest_successful_summary(self) -> Optional[IMSUpload]:
        """Summary (Özet) kayıtları başarıyla oluşmuş son yüklemeyi getirir."""
        return (
            self.session.query(IMSUpload)
            .filter(IMSUpload.status == "COMPLETED")
            .filter(IMSUpload.summary_record_count > 0)
            .order_by(desc(IMSUpload.completed_at))
            .first()
        )

    def load_recent_failed_uploads(self, limit: int = 3) -> List[IMSUpload]:
        """En son başarısız (FAILED) olan yüklemeleri getirir."""
        return (
            self.session.query(IMSUpload)
            .filter_by(status="FAILED")
            .order_by(desc(IMSUpload.uploaded_at))
            .limit(limit)
            .all()
        )

    def load_processing_upload_count(self) -> int:
        """Şu an işlemekte (PROCESSING) olan yüklemelerin sayısını getirir."""
        return self.session.query(IMSUpload).filter_by(status="PROCESSING").count()

    def load_import_status(self) -> Optional[Row]:
        """Son yapılan işlemin (upload) sadece statü bilgisini barındıran Row objesini döndürür."""
        return (
            self.session.query(IMSUpload.status)
            .order_by(desc(IMSUpload.uploaded_at))
            .first()
        )

    def load_setting(self, key: str) -> Optional[Setting]:
        """Belirtilen anahtara (key) sahip tek bir sistem ayarını (Setting) getirir."""
        return self.session.query(Setting).filter_by(setting_key=key).first()

    def load_system_settings(self) -> List[Setting]:
        """Veritabanındaki tüm konfigürasyon ve sistem ayarlarını getirir."""
        return self.session.query(Setting).all()

    def load_settings_by_keys(self, keys: List[str]) -> List[Setting]:
        """Sadece parametre ile talep edilen spesifik ayar (Setting) ORM objelerini getirir."""
        if not keys:
            return []
        return self.session.query(Setting).filter(Setting.setting_key.in_(keys)).all()

    def load_pending_manual_match_count(self) -> int:
        """Manuel eşleştirme bekleyen kayıtların sayısını getirir."""
        if not ManualMatchQueue:
            return 0
        return self.session.query(ManualMatchQueue).filter_by(status="PENDING").count()

    def load_resolved_representative_match_count(self) -> int:
        """Çözümlenmiş temsilci eşleştirme kayıtlarının sayısını getirir."""
        if not RepresentativeMatch:
            return 0
        return self.session.query(RepresentativeMatch).count()

    def load_resolved_product_match_count(self) -> int:
        """Çözümlenmiş ürün eşleştirme kayıtlarının sayısını getirir."""
        if not ProductMatch:
            return 0
        return self.session.query(ProductMatch).count()

    def load_pending_manual_matches(self, limit: Optional[int] = None) -> List[Any]:
        """Manuel eşleştirme bekleyen (PENDING) ham kayıtları listeler."""
        if not ManualMatchQueue:
            return []
            
        query = self.session.query(ManualMatchQueue).filter_by(status="PENDING").order_by(desc(ManualMatchQueue.created_at))
        if limit:
            query = query.limit(limit)
            
        return query.all()

    def load_last_import_audit(self) -> Optional[Any]:
        """Son yapılan yüklemeye ait ham denetim (audit) logunu getirir."""
        if not ImportAuditLog:
            return None
            
        return self.session.query(ImportAuditLog).order_by(desc(ImportAuditLog.created_at)).first()

    def load_last_completed_period(self) -> Optional[Row]:
        """
        Sistemde verisi bulunan son yıl ve ay bilgisini SQLAlchemy Row olarak döndürür.
        """
        return (
            self.session.query(IMSSummary.year, IMSSummary.month)
            .order_by(desc(IMSSummary.year), desc(IMSSummary.month))
            .first()
        )

    def load_available_years(self) -> Sequence[Row]:
        """
        Sistemde kayıtlı bulunan benzersiz (distinct) yılları SQLAlchemy Row dizisi olarak listeler.
        Hiçbir mapper veya liste dönüştürücü (list comprehension) kullanmaz.
        """
        return (
            self.session.query(IMSSummary.year)
            .distinct()
            .order_by(desc(IMSSummary.year))
            .all()
        )

    def load_available_months(self, year: int) -> Sequence[Row]:
        """Seçilen yıla ait benzersiz (distinct) ayları SQLAlchemy Row dizisi olarak listeler."""
        return (
            self.session.query(IMSSummary.month)
            .filter_by(year=year)
            .distinct()
            .order_by(desc(IMSSummary.month))
            .all()
        )

    def load_available_quarters(self, year: int) -> Sequence[Row]:
        """Seçilen yıla ait benzersiz (distinct) çeyrekleri SQLAlchemy Row dizisi olarak listeler."""
        return (
            self.session.query(IMSSummary.quarter)
            .filter_by(year=year)
            .distinct()
            .order_by(desc(IMSSummary.quarter))
            .all()
  )
