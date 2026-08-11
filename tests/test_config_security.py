import importlib
import os
import unittest


class ConfigSecurityTestCase(unittest.TestCase):
    def _reload_config_module(self):
        import config

        return importlib.reload(config)

    def test_production_requires_secret_key(self):
        original_secret = os.environ.pop("SECRET_KEY", None)
        original_app_env = os.environ.get("APP_ENV")

        try:
            os.environ["APP_ENV"] = "production"
            with self.assertRaises(RuntimeError):
                self._reload_config_module()
        finally:
            if original_secret is not None:
                os.environ["SECRET_KEY"] = original_secret
            else:
                os.environ.pop("SECRET_KEY", None)

            if original_app_env is not None:
                os.environ["APP_ENV"] = original_app_env
            else:
                os.environ.pop("APP_ENV", None)
            self._reload_config_module()

    def test_non_production_can_use_dev_secret(self):
        original_secret = os.environ.pop("SECRET_KEY", None)
        original_app_env = os.environ.get("APP_ENV")

        try:
            os.environ["APP_ENV"] = "development"
            config_module = self._reload_config_module()
            self.assertIsInstance(config_module.Config.SECRET_KEY, str)
            self.assertGreaterEqual(len(config_module.Config.SECRET_KEY), 32)
            self.assertFalse(config_module.Config.STRICT_SCHEMA_VALIDATION)
        finally:
            if original_secret is not None:
                os.environ["SECRET_KEY"] = original_secret
            else:
                os.environ.pop("SECRET_KEY", None)

            if original_app_env is not None:
                os.environ["APP_ENV"] = original_app_env
            else:
                os.environ.pop("APP_ENV", None)
            self._reload_config_module()

    def test_production_with_secret_key_is_allowed(self):
        original_secret = os.environ.get("SECRET_KEY")
        original_app_env = os.environ.get("APP_ENV")

        try:
            os.environ["APP_ENV"] = "production"
            os.environ["SECRET_KEY"] = "prod-secret"
            config_module = self._reload_config_module()
            self.assertEqual("prod-secret", config_module.Config.SECRET_KEY)
            self.assertTrue(config_module.Config.STRICT_SCHEMA_VALIDATION)
        finally:
            if original_secret is not None:
                os.environ["SECRET_KEY"] = original_secret
            else:
                os.environ.pop("SECRET_KEY", None)

            if original_app_env is not None:
                os.environ["APP_ENV"] = original_app_env
            else:
                os.environ.pop("APP_ENV", None)
            self._reload_config_module()


if __name__ == "__main__":
    unittest.main()
