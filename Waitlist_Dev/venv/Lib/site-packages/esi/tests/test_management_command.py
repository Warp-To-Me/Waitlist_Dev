from unittest.mock import patch
from io import StringIO

from django.contrib.auth.models import User
from django.test import TestCase
from django.core.management import call_command as base_call_command

from . import _generate_token, _store_as_Token

from esi.errors import (
    TokenInvalidError,
    NotRefreshableTokenError
)

from oauthlib.oauth2.rfc6749.errors import InvalidGrantError, \
    InvalidTokenError, \
    InvalidClientIdError


@patch('esi.models.Token.delete')
@patch('requests_oauthlib.OAuth2Session.refresh_token')
@patch('esi.models.Token.refresh')
class TestSSOMigrations(TestCase):
    """tests for SSOv1 to SSOv2 Migration command"""

    def setUp(self):

        character_id = 1001
        character_name = 'Batman'

        self.user = User.objects.create_user(
            character_name,
            'abc@example.com',
            'password'
        )
        self.token_v1 = _store_as_Token(
            _generate_token(
                character_id=character_id,
                character_name=character_name,
                scopes=['esi-universe.read_structures.v1'],
                sso_version=1
            ),
            self.user
        )
        self.token_v3 = _store_as_Token(
            _generate_token(
                character_id=character_id,
                character_name=character_name,
                scopes=['esi-universe.read_structures.v1'],
                sso_version=1
            ),
            self.user
        )
        self.token_v4 = _store_as_Token(
            _generate_token(
                character_id=character_id,
                character_name=character_name,
                scopes=['esi-universe.read_structures.v1'],
                sso_version=1
            ),
            self.user
        )
        self.token_v5 = _store_as_Token(
            _generate_token(
                character_id=character_id,
                character_name=character_name,
                scopes=['esi-universe.read_structures.v1'],
                sso_version=1
            ),
            self.user
        )
        self.token_v2 = _store_as_Token(
            _generate_token(
                character_id=character_id,
                character_name=character_name,
                scopes=['publicdata']

            ),
            self.user
        )

    def call_command(self, *args, **kwargs):
        std_out = StringIO()
        std_err = StringIO()
        base_call_command(
            "migrate_to_ssov2",
            *args,
            stdout=std_out,
            stderr=std_err,
            **kwargs,
        )
        return (std_out.getvalue(), std_err.getvalue())

    def test_ignore_sso_v1(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):
        mock_v1_refresh.return_value = {
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }

        self.call_command("--skip-v1-checks", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 1)
        self.assertEqual(mock_v1_refresh.call_count, 0)
        self.assertEqual(mock_delete.call_count, 0)

    def test_normal_refresh(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.return_value = {
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }
        self.call_command("-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 1)
        self.assertEqual(mock_v1_refresh.call_count, 1)
        self.assertEqual(mock_delete.call_count, 0)

    def test_normal_refresh_all(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.return_value = {
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }
        self.call_command()

        self.assertEqual(mock_v2_refresh.call_count, 4)
        self.assertEqual(mock_v1_refresh.call_count, 4)
        self.assertEqual(mock_delete.call_count, 0)

    def test_fail_v1_pre_refresh_ignore(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.side_effect = InvalidGrantError
        self.call_command("-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 0)
        self.assertEqual(mock_v1_refresh.call_count, 1)
        self.assertEqual(mock_delete.call_count, 0)

    def test_fail_v1_pre_refresh_delete_InvalidGrantError(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.side_effect = InvalidGrantError
        self.call_command("--purge", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 0)
        self.assertEqual(mock_v1_refresh.call_count, 1)
        self.assertEqual(mock_delete.call_count, 1)

    def test_fail_v1_pre_refresh_delete_InvalidTokenError(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.side_effect = InvalidTokenError
        self.call_command("--purge", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 0)
        self.assertEqual(mock_v1_refresh.call_count, 1)
        self.assertEqual(mock_delete.call_count, 1)

    def test_fail_v1_pre_refresh_delete_InvalidClientIdError(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.side_effect = InvalidClientIdError
        self.call_command("--purge", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 0)
        self.assertEqual(mock_v1_refresh.call_count, 1)
        self.assertEqual(mock_delete.call_count, 1)

    def test_fail_v1_pre_refresh_delete_Exception(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.side_effect = Exception
        self.call_command("--purge", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 0)
        self.assertEqual(mock_v1_refresh.call_count, 1)
        self.assertEqual(mock_delete.call_count, 1)

    def test_fail_v2_refresh_ignore(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v2_refresh.side_effect = TokenInvalidError
        self.call_command("--purge", "--skip-v1-checks", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 1)
        self.assertEqual(mock_v1_refresh.call_count, 0)
        self.assertEqual(mock_delete.call_count, 1)

    def test_fail_v2_refresh_delete(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v2_refresh.side_effect = TokenInvalidError
        self.call_command("--purge", "--skip-v1-checks", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 1)
        self.assertEqual(mock_v1_refresh.call_count, 0)
        self.assertEqual(mock_delete.call_count, 1)

    def test_v1_pass_v2_fail_v1_pass(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.return_value = {
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }
        mock_v2_refresh.side_effect = TokenInvalidError

        self.call_command("--purge", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 1)
        self.assertEqual(mock_v1_refresh.call_count, 2)
        self.assertEqual(mock_delete.call_count, 0)

    def test_v1_pass_v2_fail_v1_fail_ignore(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.side_effect = [{
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }, InvalidGrantError]
        mock_v2_refresh.side_effect = TokenInvalidError

        self.call_command("-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 1)
        self.assertEqual(mock_v1_refresh.call_count, 2)
        self.assertEqual(mock_delete.call_count, 0)

    def test_v1_pass_v2_fail_v1_fail_delete(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.side_effect = [{
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }, InvalidGrantError]
        mock_v2_refresh.side_effect = TokenInvalidError

        self.call_command("--purge", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 1)
        self.assertEqual(mock_v1_refresh.call_count, 2)
        self.assertEqual(mock_delete.call_count, 1)

    def test_v2_fail_non_refresh_delete(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.side_effect = [{
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }]
        mock_v2_refresh.side_effect = NotRefreshableTokenError

        self.call_command("--purge", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 1)
        self.assertEqual(mock_v1_refresh.call_count, 1)
        self.assertEqual(mock_delete.call_count, 1)

    def test_v2_fail_ignore(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.side_effect = [{
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }]
        mock_v2_refresh.side_effect = TokenInvalidError

        self.call_command("--skip-v1-checks", "-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 1)
        self.assertEqual(mock_v1_refresh.call_count, 0)
        self.assertEqual(mock_delete.call_count, 0)

    def test_v2_fail_non_refresh_ignore(
        self, mock_v2_refresh, mock_v1_refresh, mock_delete
    ):

        mock_v1_refresh.side_effect = [{
            'access_token': 'access_token_2',
            'refresh_token': 'refresh_token_2'
        }]
        mock_v2_refresh.side_effect = NotRefreshableTokenError

        self.call_command("-n 1")

        self.assertEqual(mock_v2_refresh.call_count, 1)
        self.assertEqual(mock_v1_refresh.call_count, 1)
        self.assertEqual(mock_delete.call_count, 0)
