"""Centralized reporting period service determining the active business IMS period."""

from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class PeriodService:
    """Single source of truth for resolving the active reporting period for enterprise dashboards and analytics."""

    @classmethod
    def get_active_period(cls, year=None, month=None):
        """
        Resolves active period based on Enterprise priority:
        1. Explicitly requested year/month.
        2. Database latest COMPLETED IMS upload.
        3. Safe fallback to datetime.now() for empty systems.
        
        Returns a complete period object (dict).
        """
        now = datetime.now()
        period = {
            "year": now.year,
            "month": now.month,
            "quarter": ((now.month - 1) // 3) + 1,
            "week_number": 1,
            "upload_id": None
        }

        try:
            from flask import has_app_context
            if has_app_context():
                from app.models import IMSUpload
                if year is not None and month is not None:
                    # Priority 1: Explicit parameters provided
                    period["year"] = int(year)
                    period["month"] = int(month)
                    period["quarter"] = ((int(month) - 1) // 3) + 1
                    
                    # Try to fetch additional context (week, upload_id) for this explicit period
                    upload = IMSUpload.query.filter_by(
                        status='COMPLETED', year=int(year), month=int(month)
                    ).order_by(
                        IMSUpload.week_number.desc(),
                        IMSUpload.completed_at.desc(),
                        IMSUpload.id.desc(),
                    ).first()
                    
                    if upload:
                        period["week_number"] = upload.week_number or 1
                        period["upload_id"] = upload.id
                else:
                    # Priority 2: Latest COMPLETED upload
                    upload = IMSUpload.query.filter_by(status='COMPLETED').order_by(
                        IMSUpload.year.desc(),
                        IMSUpload.month.desc(),
                        IMSUpload.week_number.desc(),
                        IMSUpload.completed_at.desc(),
                        IMSUpload.id.desc(),
                    ).first()
                    if upload and upload.year and upload.month:
                        period["year"] = upload.year
                        period["month"] = upload.month
                        period["quarter"] = ((upload.month - 1) // 3) + 1
                        period["week_number"] = upload.week_number or 1
                        period["upload_id"] = upload.id
                    # If no upload, Priority 3 (datetime.now) is already set as default
            else:
                # If no app context, use explicit params if provided, otherwise fallback defaults
                if year is not None and month is not None:
                    period["year"] = int(year)
                    period["month"] = int(month)
                    period["quarter"] = ((int(month) - 1) // 3) + 1

        except Exception as e:
            logger.warning(f"PeriodService failed to fetch active period from database: {e}")
            # Ensure safe fallback continues even on DB failure
            if year is not None and month is not None:
                period["year"] = int(year)
                period["month"] = int(month)
                period["quarter"] = ((int(month) - 1) // 3) + 1

        return period
