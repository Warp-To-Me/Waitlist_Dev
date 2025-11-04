"""unit tests for esi"""

from datetime import timedelta
from unittest.mock import patch, Mock

from django.core.exceptions import ImproperlyConfigured
from django.contrib.auth.models import User
from django.utils import timezone
from django.test import TestCase

from oauthlib.oauth2.rfc6749.errors import InvalidGrantError, \
    MissingTokenError, InvalidClientError, InvalidTokenError, \
    InvalidClientIdError

from esi.errors import TokenInvalidError, NotRefreshableTokenError, \
    TokenExpiredError, IncompleteResponseError, TokenError
from esi.models import Token

from . import _generate_token, _store_as_Token
from .factories_2 import CallbackRedirectFactory, ScopeFactory, TokenFactory


MODULE_PATH = "esi.models"


class TestScope(TestCase):
    def test_should_return_str(self):
        # given
        obj = ScopeFactory.build(name="dummy_scope")
        # when/then
        self.assertEqual(str(obj), "dummy_scope")

    def test_should_return_friendly_name_1(self):
        # given
        obj = ScopeFactory.build(name="dummy_scope")
        # when/then
        self.assertEqual(obj.friendly_name, "dummy_scope")

    def test_should_return_friendly_name_2(self):
        # given
        obj = ScopeFactory.build(name="test.dummy_scope.test")
        # when/then
        self.assertEqual(obj.friendly_name, "dummy scope")


class TestToken2(TestCase):
    def test_should_return_str(self):
        # given
        scope = ScopeFactory(name="dummy_scope")
        token = TokenFactory(character_name="Bruce Wayne", scopes=[scope])
        # when/then
        self.assertEqual(str(token), "Bruce Wayne - dummy_scope")

    def test_should_return_str_not_created(self):
        # given
        token = TokenFactory.build(character_name="Bruce Wayne")
        # when/then
        self.assertEqual(str(token), "Bruce Wayne - ")

    def test_should_return_repr(self):
        # given
        scope = ScopeFactory(name="dummy_scope")
        token = TokenFactory(
            id=99, character_id=1001, character_name="Bruce Wayne", scopes=[scope]
        )
        # when/then
        self.assertEqual(repr(token), "<Token(id=99): 1001, Bruce Wayne>")

    def test_should_find_token(self):
        # given
        scope = ScopeFactory(name="dummy_scope")
        token = TokenFactory(character_id=1001, scopes=[scope])
        TokenFactory()
        # when
        result = Token.get_token(1001, ['dummy_scope'])
        # then
        self.assertEqual(token, result)

    def test_should_return_false_when_token_not_found(self):
        # given
        scope = ScopeFactory(name="dummy_scope")
        TokenFactory(character_id=1001, scopes=[scope])
        # when
        result = Token.get_token(1001, ['unknown'])
        # then
        self.assertFalse(result)

    def test_should_be_able_to_refresh(self):
        # given
        token = TokenFactory.build()
        # when/then
        self.assertTrue(token.can_refresh)

    def test_should_not_be_able_to_refresh(self):
        # given
        token = TokenFactory.build(refresh_token=None)
        # when/then
        self.assertFalse(token.can_refresh)


@patch(MODULE_PATH + ".Token.refresh", spec=True)
class TestTokenRefreshOrDelete(TestCase):
    def test_should_refresh_token(self, mock_token_refresh):
        # given
        token = TokenFactory()
        # when
        token.refresh_or_delete()
        # then
        self.assertTrue(mock_token_refresh.called)
        self.assertTrue(Token.objects.filter(pk=token.pk).exists())

    def test_should_delete_token_with_errors(self, mock_token_refresh):
        # given
        mock_token_refresh.side_effect = TokenError
        token = TokenFactory()
        # when
        token.refresh_or_delete()
        # then
        self.assertTrue(mock_token_refresh.called)
        self.assertFalse(Token.objects.filter(pk=token.pk).exists())

    def test_should_not_delete_token_with_incomplete_response_error(self, mock_token_refresh):
        # given
        mock_token_refresh.side_effect = IncompleteResponseError
        token = TokenFactory()
        # when
        with self.assertRaises(IncompleteResponseError):
            token.refresh_or_delete()
        # then
        self.assertTrue(mock_token_refresh.called)
        self.assertTrue(Token.objects.filter(pk=token.pk).exists())


class TestToken(TestCase):
    def setUp(self):

        character_id = 1000
        character_name = 'Bruce Wayne'

        self.user = User.objects.create_user(
            character_name,
            'abc@example.com',
            'password'
        )
        self.token = _store_as_Token(
            _generate_token(
                character_id=character_id,
                character_name=character_name,
                scopes=['esi-universe.read_structures.v1']
            ),
            self.user
        )

    @patch(MODULE_PATH + '.app_settings.ESI_TOKEN_VALID_DURATION', 120)
    def test_expires(self):
        self.assertEqual(
            self.token.created + timedelta(seconds=120),
            self.token.expires
        )

    @patch(MODULE_PATH + '.app_settings.ESI_TOKEN_VALID_DURATION', 120)
    def test_not_expired(self):
        self.assertFalse(self.token.expired)

    @patch(MODULE_PATH + '.app_settings.ESI_TOKEN_VALID_DURATION', 120)
    def test_has_expired(self):
        self.token.created -= timedelta(121)
        self.assertTrue(self.token.expired)

    def test_refresh_normal_1(self):
        mock_auth = Mock()
        mock_session = Mock()
        mock_session.refresh_token.return_value = {
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }

        self.token.refresh(mock_session, mock_auth)
        self.assertEqual(
            self.token.refresh_token, 'refresh_token_2'
        )
        self.assertEqual(
            self.token.access_token, 'access_token_2'
        )
        self.assertGreaterEqual(
            self.token.created, timezone.now() - timedelta(seconds=60)
        )

    @patch(MODULE_PATH + '.HTTPBasicAuth', autospec=True)
    @patch(MODULE_PATH + '.OAuth2Session', autospec=True)
    def test_refresh_normal_2(self, mock_OAuth2Session, mock_HTTPBasicAuth):
        mock_session = Mock()
        mock_session.refresh_token.return_value = {
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }
        mock_OAuth2Session.return_value = mock_session

        self.token.refresh()
        self.assertEqual(
            self.token.refresh_token,
            'refresh_token_2'
        )
        self.assertEqual(
            self.token.access_token,
            'access_token_2'
        )
        self.assertGreaterEqual(
            self.token.created,
            timezone.now() - timedelta(seconds=60))

    def test_valid_access_token(self):
        self.assertFalse(self.token.expired)
        self.assertEqual(self.token.valid_access_token(), 'access_token')

    @patch(MODULE_PATH + '.HTTPBasicAuth', autospec=True)
    @patch(MODULE_PATH + '.OAuth2Session', autospec=True)
    @patch(MODULE_PATH + '.app_settings.ESI_TOKEN_VALID_DURATION', 120)
    def test_valid_access_token_refresh(self, mock_OAuth2Session, mock_HTTPBasicAuth):
        mock_session = Mock()
        mock_session.refresh_token.return_value = {
            'access_token': 'access_token_new',
            'refresh_token': 'refresh_token_2'
        }
        mock_OAuth2Session.return_value = mock_session

        self.token.created -= timedelta(121)
        self.assertTrue(self.token.expired)
        self.assertEqual(
            self.token.valid_access_token(), 'access_token_new')

    @patch(MODULE_PATH + '.HTTPBasicAuth', autospec=True)
    @patch(MODULE_PATH + '.OAuth2Session', autospec=True)
    @patch(MODULE_PATH + '.app_settings.ESI_TOKEN_VALID_DURATION', 120)
    def test_valid_access_token_cant_refresh(
        self, mock_OAuth2Session, mock_HTTPBasicAuth
    ):
        self.token.refresh_token = None
        self.token.created -= timedelta(121)
        self.assertTrue(self.token.expired)
        with self.assertRaises(TokenExpiredError):
            self.token.valid_access_token()

    def test_refresh_errors_1(self):
        mock_auth = Mock()
        mock_session = Mock()
        mock_session.refresh_token.return_value = {
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }
        self.token.refresh_token = None
        with self.assertRaises(NotRefreshableTokenError):
            self.token.refresh(mock_session, mock_auth)

    def test_refresh_errors_2(self):
        mock_auth = Mock()
        mock_session = Mock()

        mock_session.refresh_token.side_effect = InvalidGrantError
        with self.assertRaises(TokenInvalidError):
            self.token.refresh(mock_session, mock_auth)

        mock_session.refresh_token.side_effect = InvalidTokenError
        with self.assertRaises(TokenInvalidError):
            self.token.refresh(mock_session, mock_auth)

        mock_session.refresh_token.side_effect = InvalidClientIdError
        with self.assertRaises(TokenInvalidError):
            self.token.refresh(mock_session, mock_auth)

        mock_session.refresh_token.side_effect = MissingTokenError
        with self.assertRaises(IncompleteResponseError):
            self.token.refresh(mock_session, mock_auth)

        mock_session.refresh_token.side_effect = InvalidClientError
        with self.assertRaises(ImproperlyConfigured):
            self.token.refresh(mock_session, mock_auth)

    @patch(MODULE_PATH + '.esi_client_factory', autospec=True)
    def test_get_esi_client(self, mock_esi_client):
        mock_esi_client.return_value = "Johnny"
        x = self.token.get_esi_client()
        self.assertEqual(x, "Johnny")
        self.assertEqual(mock_esi_client.call_count, 1)

    """
    @patch('esi.managers.TokenManager')
    def test_get_token_data(self, mock_decode_jwt):
        mock_decode_jwt._decode_jwt.return_value = \
            _generate_token(
                99, 'Bruce Wayne', scopes=[
                    'esi-calendar.read_calendar_events.v1',
                    'esi-location.read_location.v1',
                    'esi-location.read_ship_type.v1',
                    'esi-unknown-scope'
                ]
            )
        data = self.token.get_token_data(access_token='access_token_2')
        self.assertEqual(data['name'], "Bruce Wayne")
    """
    @patch(MODULE_PATH + '.Token.get_token_data')
    def test_update_token_data_normal_1(self, mock_get_token_data):
        mock_get_token_data.return_value = _generate_token(99, 'Bruce Wayne')
        self.token.update_token_data()
        self.token.refresh_from_db()
        self.assertEqual(
            self.token.character_id,
            99
        )
        self.assertEqual(
            self.token.character_name,
            'Bruce Wayne'
        )
        self.assertEqual(
            self.token.character_owner_hash,
            'character_owner_hash'
        )
        self.assertEqual(
            self.token.token_type,
            'character'
        )

    @patch(MODULE_PATH + '.HTTPBasicAuth', autospec=True)
    @patch(MODULE_PATH + '.OAuth2Session', autospec=True)
    @patch(MODULE_PATH + '.Token.get_token_data')
    def test_update_token_data_normal_2(
        self,
        mock_get_token_data,
        mock_OAuth2Session,
        mock_HTTPBasicAuth
    ):
        mock_session = Mock()
        mock_session.refresh_token.return_value = {
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }
        mock_OAuth2Session.return_value = mock_session

        mock_get_token_data.return_value = {
            'character_id': 99,
            'name': 'CharacterName',
            'owner': 'CharacterOwnerHash',
            'token_type': 'character',
        }
        self.token.created -= timedelta(121)

        self.token.update_token_data()
        self.token.refresh_from_db()
        self.assertEqual(
            self.token.character_id,
            99
        )

    @patch(MODULE_PATH + '.Token.get_token_data')
    def test_update_token_data_normal_3(self, mock_get_token_data):
        mock_get_token_data.return_value = {
            'character_id': 99,
            'name': 'CharacterName',
            'owner': 'CharacterOwnerHash',
            'token_type': 'Character',
        }
        self.token.update_token_data(commit=False)
        self.assertEqual(
            self.token.character_id,
            99
        )
        self.assertEqual(
            self.token.character_name,
            'CharacterName'
        )
        self.assertEqual(
            self.token.character_owner_hash,
            'CharacterOwnerHash'
        )
        self.assertEqual(
            self.token.token_type,
            'Character'
        )

    @patch(MODULE_PATH + '.Token.get_token_data', auto_spec=True, unsafe=True)
    def test_update_token_data_error(
        self,
        mock_get_token_data
    ):
        self.token.refresh_token = None
        self.token.created -= timedelta(121)
        with self.assertRaises(TokenExpiredError):
            self.token.update_token_data()


class TestCallbackRedirect(TestCase):
    def test_should_return_str(self):
        # given
        cb = CallbackRedirectFactory.build(session_key="abc", url="/green/alpha")
        # when/then
        self.assertEqual("abc: /green/alpha", str(cb))

    def test_should_return_repr(self):
        # given
        cb = CallbackRedirectFactory(session_key="abc", url="/green/alpha")
        # when/then
        expected = f"<CallbackRedirect(pk={cb.pk}): abc to /green/alpha>"
        self.assertEqual(expected, repr(cb))
