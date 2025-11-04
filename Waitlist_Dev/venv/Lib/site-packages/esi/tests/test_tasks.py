from datetime import timedelta
from unittest.mock import patch

from celery import current_app as celery_app
from django.utils.timezone import now

from esi.models import CallbackRedirect, Token
from esi.tasks import cleanup_callbackredirect, cleanup_token, cleanup_token_subset

from . import NoSocketsTestCase
from .factories_2 import TokenFactory, CallbackRedirectFactory

from math import ceil

MANAGERS_PATH = "esi.managers"
MODELS_PATH = "esi.models"
TASKS_PATH = "esi.tasks"


class CeleryTestCase(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True


class TestCleanupCallbackredirect(CeleryTestCase):
    def test_should_remove_expired(self) -> None:
        # given
        cb_valid = CallbackRedirectFactory()
        with patch("django.utils.timezone.now") as m:
            m.return_value = now() - timedelta(minutes=5, seconds=1)
            cb_expired = CallbackRedirectFactory()
        # when
        cleanup_callbackredirect.delay(max_age=300)
        # then
        self.assertTrue(CallbackRedirect.objects.filter(pk=cb_valid.pk).exists())
        self.assertFalse(CallbackRedirect.objects.filter(pk=cb_expired.pk).exists())


@patch(MANAGERS_PATH + '.app_settings.ESI_TOKEN_VALID_DURATION', 120)
@patch(MODELS_PATH + '.Token.refresh', spec=True)
class TestCleanupToken(CeleryTestCase):
    def test_should_delete_orphaned_tokens(self, mock_token_refresh) -> None:
        # given
        token_1 = TokenFactory(user=None)
        token_2 = TokenFactory()
        # when
        cleanup_token.delay()
        # then
        self.assertFalse(Token.objects.filter(pk=token_1.pk).exists())
        self.assertTrue(Token.objects.filter(pk=token_2.pk).exists())

    def test_should_refresh_expired_tokens_only(self, mock_token_refresh) -> None:
        # given
        TokenFactory()
        with patch("django.utils.timezone.now") as m:
            m.return_value = now() - timedelta(minutes=3)
            TokenFactory()
        # when
        cleanup_token.delay()
        # then
        self.assertEqual(mock_token_refresh.call_count, 1)


class TestCleanupTokenSubset(CeleryTestCase):
    @patch(MANAGERS_PATH + '.app_settings.ESI_TOKEN_VALID_DURATION', 120)
    @patch(TASKS_PATH + ".refresh_or_delete_token.apply_async")
    def test_should_delete_orphaned_tokens(self, mock_token_refresh) -> None:
        # given
        orphaned = TokenFactory(user=None)
        valid = TokenFactory()
        # when
        cleanup_token_subset.delay()
        # then
        self.assertFalse(Token.objects.filter(pk=orphaned.pk).exists())
        self.assertTrue(Token.objects.filter(pk=valid.pk).exists())

    @patch(MANAGERS_PATH + '.app_settings.ESI_TOKEN_VALID_DURATION', 1)
    @patch(TASKS_PATH + ".refresh_or_delete_token.apply_async")
    def test_should_refresh_fraction_of_expired_tokens(self, mock_token_refresh) -> None:
        # given
        num_expired = 100
        for _ in range(num_expired):
            TokenFactory(refresh_token="some_token")
        # patch time so all tokens are expired
        with patch("django.utils.timezone.now") as m:
            m.return_value = now() + timedelta(minutes=5)
            # when
            cleanup_token_subset.delay(fraction=10)
        # then
        expected_count = ceil(num_expired / 10)
        self.assertEqual(mock_token_refresh.call_count, expected_count)

    @patch(MANAGERS_PATH + '.app_settings.ESI_TOKEN_VALID_DURATION', 1)
    @patch("esi.tasks.refresh_or_delete_token.apply_async")
    def test_should_refresh_expired_tokens_only(self, mock_token_refresh) -> None:
        # given
        TokenFactory()
        with patch("django.utils.timezone.now") as m:
            m.return_value = now() - timedelta(minutes=3)
            TokenFactory()
        # when
        cleanup_token_subset.delay()
        # then
        self.assertEqual(mock_token_refresh.call_count, 1)

    @patch(MANAGERS_PATH + '.app_settings.ESI_TOKEN_VALID_DURATION', 1)
    @patch(TASKS_PATH + ".refresh_or_delete_token.apply_async")
    def test_should_log_and_exit_gracefully_with_no_tokens(self, mock_token_refresh) -> None:
        # when
        cleanup_token_subset.delay()
        # then
        self.assertEqual(Token.objects.count(), 0)
        mock_token_refresh.assert_not_called()
