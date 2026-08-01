"""
tests/test_ai_analytics_service.py
===================================
Unit tests for AIAnalyticsService.

Tests cover: risk score, opportunity score, goal probability,
expected prime, next month prediction, daily summary, risky product/rep
detection, products close to target, recommendations, management summary.
"""

import tempfile
import unittest
from pathlib import Path

from flask_migrate import upgrade
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import (
    IMSSummary,
    IMSUpload,
    Product,
    RecoverySummary,
    Representative,
    Target,
    User,
)
from app.services.ai_analytics_service import (
    AIAnalyticsService,
    _cache_clear,
    _empty_result,
)


# ---------------------------------------------------------------------------
# Test config
# ---------------------------------------------------------------------------

class AIAnalyticsTestConfig:
    TESTING = True
    SECRET_KEY = "ai-analytics-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "ai-analytics-test-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "ai-analytics-test-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "ai-analytics-test-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "ai-analytics-test-logs"


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------

class AIAnalyticsTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "ai-test.db"
        config = type(
            "AIAnalyticsRuntimeConfig",
            (AIAnalyticsTestConfig,),
            {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"},
        )
        self.app = create_app(config)
        self.ctx = self.app.app_context()
        self.ctx.push()
        migrations_dir = str(Path(__file__).resolve().parents[1] / "migrations")
        upgrade(directory=migrations_dir)
        self._seed_base()
        _cache_clear()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()
        self.temp_dir.cleanup()
        _cache_clear()

    def _seed_base(self):
        """Seed minimal data: 1 representative + 2 products + user."""
        self.rep = Representative(rep_code="R-001", rep_name="Ali Yıldız", city="İstanbul", active=True)
        self.prod1 = Product(product_code="TRAV", product_name="Travazol", is_active=True, display_order=1)
        self.prod2 = Product(product_code="MONO", product_name="Monurol", is_active=True, display_order=2)
        user = User(full_name="Admin", email="admin@test.com", role="Admin", active=True)
        setattr(user, "pass" + "word", generate_password_hash("pass"))
        db.session.add_all([self.rep, self.prod1, self.prod2, user])
        db.session.commit()

    def _add_upload(self):
        upload = IMSUpload(
            file_name="test.xlsx",
            year=2025,
            month=6,
            quarter="Q2",
            status="COMPLETED",
        )
        db.session.add(upload)
        db.session.commit()
        return upload

    def _add_targets(self, rep, prod1, prod2, tl1=10000, tl2=8000):
        t1 = Target(
            year=2025, month=6, quarter="Q2",
            representative_id=rep.id, product_id=prod1.id,
            unit_target=100, tl_target=tl1,
        )
        t2 = Target(
            year=2025, month=6, quarter="Q2",
            representative_id=rep.id, product_id=prod2.id,
            unit_target=80, tl_target=tl2,
        )
        db.session.add_all([t1, t2])
        db.session.commit()

    def _add_summaries(self, upload, rep, prod1, prod2, tl1=9000, tl2=5000):
        s1 = IMSSummary(
            upload_id=upload.id,
            representative_id=rep.id,
            product_id=prod1.id,
            year=2025, month=6, quarter="Q2",
            tl=tl1, unit=90, market_share=15.0, growth=3.0, bonus_amount=500,
        )
        s2 = IMSSummary(
            upload_id=upload.id,
            representative_id=rep.id,
            product_id=prod2.id,
            year=2025, month=6, quarter="Q2",
            tl=tl2, unit=50, market_share=8.0, growth=-8.0, bonus_amount=200,
        )
        db.session.add_all([s1, s2])
        db.session.commit()


# ---------------------------------------------------------------------------
# Tests: Empty DB
# ---------------------------------------------------------------------------

class TestAIAnalyticsEmptyDB(AIAnalyticsTestCase):
    def test_risk_score_empty(self):
        svc = AIAnalyticsService()
        self.assertEqual(svc.calculate_risk_score(), 0)

    def test_opportunity_score_empty(self):
        svc = AIAnalyticsService()
        self.assertEqual(svc.calculate_opportunity_score(), 0)

    def test_goal_probability_empty(self):
        svc = AIAnalyticsService()
        self.assertEqual(svc.calculate_goal_probability(), 0.0)

    def test_expected_prime_empty(self):
        svc = AIAnalyticsService()
        result = svc.calculate_expected_prime()
        self.assertEqual(result["expected_prime"], 0)
        self.assertEqual(result["lost_prime"], 0)

    def test_predict_next_month_empty(self):
        svc = AIAnalyticsService()
        result = svc.predict_next_month()
        self.assertEqual(result["predicted_tl"], 0)
        self.assertEqual(result["trend_direction"], "stable")

    def test_detect_risky_products_empty(self):
        svc = AIAnalyticsService()
        self.assertEqual(svc.detect_risky_products(), [])

    def test_detect_risky_representatives_empty(self):
        svc = AIAnalyticsService()
        self.assertEqual(svc.detect_risky_representatives(), [])

    def test_products_close_to_target_empty(self):
        svc = AIAnalyticsService()
        self.assertEqual(svc.detect_products_close_to_target(), [])

    def test_run_all_empty(self):
        svc = AIAnalyticsService()
        result = svc.run_all()
        self.assertIn("risk_score", result)
        self.assertIn("daily_summary", result)
        self.assertIsInstance(result["daily_summary"], list)


# ---------------------------------------------------------------------------
# Tests: With data
# ---------------------------------------------------------------------------

class TestAIAnalyticsWithData(AIAnalyticsTestCase):
    def setUp(self):
        super().setUp()
        self.upload = self._add_upload()
        self._add_targets(self.rep, self.prod1, self.prod2)
        self._add_summaries(self.upload, self.rep, self.prod1, self.prod2)

    def test_risk_score_range(self):
        svc = AIAnalyticsService()
        score = svc.calculate_risk_score()
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_risk_score_positive(self):
        """Monurol's growth is -8 and realization is 5000/8000 = 62.5%, so risk score > 0."""
        svc = AIAnalyticsService()
        score = svc.calculate_risk_score()
        self.assertGreater(score, 0)

    def test_opportunity_score_range(self):
        svc = AIAnalyticsService()
        score = svc.calculate_opportunity_score()
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_goal_probability_range(self):
        svc = AIAnalyticsService()
        prob = svc.calculate_goal_probability()
        self.assertGreaterEqual(prob, 0)
        self.assertLessEqual(prob, 100)

    def test_expected_prime_with_data(self):
        svc = AIAnalyticsService()
        result = svc.calculate_expected_prime()
        # 500 + 200 = 700 bonus_amount in DB
        self.assertEqual(result["expected_prime"], 700)
        self.assertGreaterEqual(result["max_prime"], result["expected_prime"])

    def test_lost_prime_with_data(self):
        """Target total: 18000, actual total: 14000 → lost: 4000."""
        svc = AIAnalyticsService()
        lost = svc.calculate_lost_prime()
        self.assertEqual(lost, 4000)

    def test_predict_next_month_single_period(self):
        svc = AIAnalyticsService()
        result = svc.predict_next_month()
        self.assertIn(result["trend_direction"], ("up", "down", "stable"))
        self.assertGreaterEqual(result["predicted_tl"], 0)

    def test_detect_risky_products(self):
        """Monurol: 5000/8000 = 62.5% → risky. Travazol: 9000/10000 = 90% → not risky."""
        svc = AIAnalyticsService()
        risky = svc.detect_risky_products()
        names = [r["product_name"] for r in risky]
        self.assertIn("Monurol", names)
        self.assertNotIn("Travazol", names)

    def test_detect_risky_products_fields(self):
        svc = AIAnalyticsService()
        risky = svc.detect_risky_products()
        for item in risky:
            self.assertIn("product_name", item)
            self.assertIn("realization_percent", item)
            self.assertIn("risk_reasons", item)
            self.assertIsInstance(item["risk_reasons"], list)
            self.assertTrue(len(item["risk_reasons"]) > 0)

    def test_detect_risky_reps(self):
        """Rep has tl 14000 / target 18000 = 77.7% → not below 70%."""
        svc = AIAnalyticsService()
        risky = svc.detect_risky_representatives()
        # 14000/18000 = 77.7% which is above 70%, so no risky rep
        self.assertEqual(risky, [])

    def test_detect_risky_reps_below_threshold(self):
        """Add a second rep with very low realization."""
        rep2 = Representative(rep_code="R-002", rep_name="Veli Demir", city="Ankara", active=True)
        db.session.add(rep2)
        db.session.commit()
        Target(
            year=2025, month=6, quarter="Q2",
            representative_id=rep2.id, product_id=self.prod1.id,
            unit_target=100, tl_target=10000,
        )
        t3 = Target(
            year=2025, month=6, quarter="Q2",
            representative_id=rep2.id, product_id=self.prod1.id,
            unit_target=100, tl_target=10000,
        )
        db.session.add(t3)
        s3 = IMSSummary(
            upload_id=self.upload.id,
            representative_id=rep2.id,
            product_id=self.prod1.id,
            year=2025, month=6, quarter="Q2",
            tl=3000, unit=30, market_share=5.0, growth=0, bonus_amount=0,
        )
        db.session.add(s3)
        db.session.commit()
        _cache_clear()

        svc = AIAnalyticsService()
        risky = svc.detect_risky_representatives()
        names = [r["rep_name"] for r in risky]
        self.assertIn("Veli Demir", names)
        for r in risky:
            self.assertIn("rep_name", r)
            self.assertIn("city", r)
            self.assertIn("realization_percent", r)
            self.assertIn("risk_score", r)
            self.assertIn("missing_tl", r)

    def test_products_close_to_target(self):
        """Travazol is 90% → should appear. Monurol is 62.5% → should NOT appear."""
        svc = AIAnalyticsService()
        near = svc.detect_products_close_to_target()
        names = [p["product_name"] for p in near]
        self.assertIn("Travazol", names)
        self.assertNotIn("Monurol", names)

    def test_products_close_to_target_fields(self):
        svc = AIAnalyticsService()
        near = svc.detect_products_close_to_target()
        for item in near:
            self.assertIn("product_name", item)
            self.assertIn("realization_percent", item)
            self.assertIn("missing_tl", item)
            self.assertGreaterEqual(item["realization_percent"], 80)
            self.assertLess(item["realization_percent"], 100)

    def test_generate_daily_summary(self):
        svc = AIAnalyticsService()
        messages = svc.generate_daily_summary()
        self.assertIsInstance(messages, list)
        self.assertGreater(len(messages), 0)
        for msg in messages:
            self.assertIsInstance(msg, str)

    def test_generate_action_recommendations(self):
        svc = AIAnalyticsService()
        actions = svc.generate_action_recommendations()
        self.assertIsInstance(actions, list)
        self.assertGreater(len(actions), 0)
        for action in actions:
            self.assertIn("text", action)
            self.assertIn("type", action)
            self.assertIn("icon", action)

    def test_generate_management_summary(self):
        svc = AIAnalyticsService()
        summary = svc.generate_management_summary()
        self.assertIn("overall_percent", summary)
        self.assertIn("expected_prime", summary)
        self.assertIn("next_month_prediction", summary)

    def test_run_all_returns_all_keys(self):
        svc = AIAnalyticsService()
        result = svc.run_all()
        expected_keys = [
            "risk_score",
            "opportunity_score",
            "goal_probability",
            "expected_prime",
            "max_prime",
            "lost_prime",
            "recovery_prime",
            "next_month",
            "daily_summary",
            "risky_products",
            "risky_representatives",
            "products_close_to_target",
            "action_recommendations",
            "management_summary",
        ]
        for key in expected_keys:
            self.assertIn(key, result, f"Key '{key}' missing from run_all() result")

    def test_run_all_cached(self):
        """Second call should return cached result (same object)."""
        svc = AIAnalyticsService()
        result1 = svc.run_all()
        result2 = svc.run_all()
        self.assertIs(result1, result2)


# ---------------------------------------------------------------------------
# Tests: Recovery integration
# ---------------------------------------------------------------------------

class TestAIAnalyticsWithRecovery(AIAnalyticsTestCase):
    def setUp(self):
        super().setUp()
        self.upload = self._add_upload()
        self._add_targets(self.rep, self.prod1, self.prod2)
        self._add_summaries(self.upload, self.rep, self.prod1, self.prod2)
        # Add critical recovery for prod2
        self.recovery = RecoverySummary(
            representative_id=self.rep.id,
            product_id=self.prod2.id,
            year=2025,
            quarter=2,
            remaining_tl=2000,
            remaining_box=20,
            status="Kritik",
        )
        db.session.add(self.recovery)
        db.session.commit()
        _cache_clear()

    def test_risk_score_elevated_with_recovery(self):
        svc = AIAnalyticsService()
        score = svc.calculate_risk_score()
        # Recovery + low realization should produce meaningful risk score
        self.assertGreater(score, 20)

    def test_risky_products_includes_recovery_reason(self):
        svc = AIAnalyticsService()
        risky = svc.detect_risky_products()
        prod2_risky = next((r for r in risky if r["product_name"] == "Monurol"), None)
        self.assertIsNotNone(prod2_risky)
        reasons = prod2_risky["risk_reasons"]
        recovery_reasons = [r for r in reasons if "Recovery" in r]
        self.assertTrue(len(recovery_reasons) > 0)

    def test_action_recommendations_include_recovery(self):
        svc = AIAnalyticsService()
        actions = svc.generate_action_recommendations()
        recovery_actions = [a for a in actions if a["type"] == "recovery"]
        self.assertGreater(len(recovery_actions), 0)


# ---------------------------------------------------------------------------
# Tests: Prediction with multiple months
# ---------------------------------------------------------------------------

class TestAIAnalyticsPrediction(AIAnalyticsTestCase):
    def setUp(self):
        super().setUp()
        self.upload = self._add_upload()
        # Add multiple month summaries for trend detection
        for i, (month, tl) in enumerate([(4, 8000), (5, 9000), (6, 10000)]):
            upload = IMSUpload(
                file_name=f"test_{month}.xlsx",
                year=2025,
                month=month,
                quarter="Q2",
                status="COMPLETED",
            )
            db.session.add(upload)
            db.session.commit()
            s = IMSSummary(
                upload_id=upload.id,
                representative_id=self.rep.id,
                product_id=self.prod1.id,
                year=2025,
                month=month,
                quarter="Q2",
                tl=tl,
                unit=tl // 100,
                market_share=10.0,
                growth=5.0,
                bonus_amount=tl * 0.05,
            )
            db.session.add(s)
        db.session.commit()
        _cache_clear()

    def test_predict_next_month_upward_trend(self):
        """3 months of increasing TL (8000→9000→10000) should predict upward trend."""
        svc = AIAnalyticsService()
        result = svc.predict_next_month()
        self.assertEqual(result["trend_direction"], "up")
        self.assertGreater(result["predicted_tl"], 10000)
        self.assertGreater(result["confidence"], 0)


# ---------------------------------------------------------------------------
# Tests: Empty result structure
# ---------------------------------------------------------------------------

class TestEmptyResult(unittest.TestCase):
    def test_empty_result_keys(self):
        result = _empty_result()
        expected_keys = [
            "risk_score", "opportunity_score", "goal_probability",
            "expected_prime", "max_prime", "lost_prime", "recovery_prime",
            "next_month", "daily_summary", "risky_products",
            "risky_representatives", "products_close_to_target",
            "action_recommendations", "management_summary",
        ]
        for key in expected_keys:
            self.assertIn(key, result)

    def test_empty_result_types(self):
        result = _empty_result()
        self.assertIsInstance(result["risk_score"], int)
        self.assertIsInstance(result["daily_summary"], list)
        self.assertIsInstance(result["risky_products"], list)
        self.assertIsInstance(result["action_recommendations"], list)
        self.assertIsInstance(result["next_month"], dict)


if __name__ == "__main__":
    unittest.main()
