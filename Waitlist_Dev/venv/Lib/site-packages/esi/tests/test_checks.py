"""unit tests for esi checks"""

from django.conf import settings
from django.test import TestCase, override_settings

from ..checks import check_sso_application_settings


class TestCheckSsoApplicationSettings(TestCase):

    @override_settings(
        ESI_SSO_CLIENT_ID='123', ESI_SSO_CLIENT_SECRET='abc', ESI_SSO_CALLBACK_URL='xyz'
    )
    def test_settings_ok(self):
        errors = check_sso_application_settings()
        self.assertEqual(len(errors), 0)

    @override_settings(ESI_SSO_CLIENT_SECRET='abc', ESI_SSO_CALLBACK_URL='xyz')
    def test_settings_incomplete_ESI_SSO_CLIENT_ID(self):
        del settings.ESI_SSO_CLIENT_ID
        errors = check_sso_application_settings()
        self.assertEqual(len(errors), 1)

    @override_settings(ESI_SSO_CLIENT_ID='123', ESI_SSO_CALLBACK_URL='xyz')
    def test_settings_incomplete_ESI_SSO_CLIENT_SECRET(self):
        del settings.ESI_SSO_CLIENT_SECRET
        errors = check_sso_application_settings()
        self.assertEqual(len(errors), 1)

    @override_settings(ESI_SSO_CLIENT_ID='123', ESI_SSO_CLIENT_SECRET='abc')
    def test_settings_incomplete_ESI_SSO_CALLBACK_URL(self):
        del settings.ESI_SSO_CALLBACK_URL
        errors = check_sso_application_settings()
        self.assertEqual(len(errors), 1)

    @override_settings(ESI_SSO_CLIENT_ID='123', ESI_SSO_CLIENT_SECRET='abc', DEBUG=True)
    def test_settings_incomplete_debug_mode(self):
        del settings.ESI_SSO_CALLBACK_URL
        errors = check_sso_application_settings()
        self.assertEqual(len(errors), 1)

    @override_settings(
        ESI_SSO_CLIENT_ID='123', ESI_SSO_CLIENT_SECRET='abc', DEBUG=False
    )
    def test_settings_incomplete_non_debug_mode(self):
        del settings.ESI_SSO_CALLBACK_URL
        errors = check_sso_application_settings()
        self.assertEqual(len(errors), 1)
