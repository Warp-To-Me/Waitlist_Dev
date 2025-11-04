"""unit tests for esi decorators"""

import logging
from unittest.mock import patch, Mock

from django.contrib.auth.models import User
from django.contrib.auth.views import redirect_to_login
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import TestCase, RequestFactory

from . import _generate_token, _store_as_Token
from ..decorators import (
    _check_callback, tokens_required, token_required, single_use_token
)
from ..models import Token, CallbackRedirect


logger = logging.getLogger(__name__)


class TestCheckCallback(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            'Bruce Wayne',
            'abc@example.com',
            'password'
        )

        self.token = _store_as_Token(
            _generate_token(
                character_id=99,
                character_name=self.user.username,
                scopes=['abc', 'xyz', '123']
            ),
            self.user
        )
        self.factory = RequestFactory()
        CallbackRedirect.objects.all().delete()

    def test_normal(self):
        logger.debug('start')
        request = self.factory.get('https://www.example.com/callback2/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        CallbackRedirect.objects.create(
            session_key=request.session.session_key,
            url='https://www.example.com/redirect/',
            state='xyz',
            token=self.token
        )
        response = _check_callback(request)
        self.assertEqual(response, self.token)

    def test_no_cb(self):
        logger.debug('start')
        request = self.factory.get('https://www.example.com/callback2/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        response = _check_callback(request)
        self.assertIsNone(response)

    def test_no_token(self):
        logger.debug('start')
        request = self.factory.get('https://www.example.com/callback2/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        CallbackRedirect.objects.create(
            session_key=request.session.session_key,
            url='https://www.example.com/redirect/',
            state='xyz'
        )

        response = _check_callback(request)
        self.assertIsNone(response)

    def test_no_session(self):
        logger.debug('start')
        request = self.factory.get('https://www.example.com/callback2/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)

        response = _check_callback(request)
        self.assertIsNone(response)


class TestTokensRequired(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            'Bruce Wayne',
            'abc@example.com',
            'password'
        )

        self.token = _store_as_Token(
            _generate_token(
                character_id=99,
                character_name=self.user.username,
                scopes=['abc', '123']
            ),
            self.user
        )
        self.factory = RequestFactory()
        CallbackRedirect.objects.all().delete()

    def test_token_already_exists(self):
        logger.debug('start')

        @tokens_required(scopes='abc')
        def my_view(request, tokens):
            return tokens

        request = self.factory.get('https://www.example.com/my_view/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        response = my_view(request)
        self.assertEqual(
            response.first(),
            self.token
        )

    def test_token_and_cb_already_exists(self):
        logger.debug('start')

        @tokens_required(scopes='abc')
        def my_view(request, tokens):
            return tokens

        request = self.factory.get('https://www.example.com/my_view/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        CallbackRedirect.objects.create(
            session_key=request.session.session_key,
            url='https://www.example.com/redirect/',
            state='xyz',
            token=self.token
        )

        response = my_view(request)
        self.assertEqual(
            response.first(),
            self.token
        )

    @patch('esi.views.sso_redirect', autospec=True)
    def test_token_does_not_exist(self, mock_sso_redirect):
        logger.debug('start')

        @tokens_required(scopes='xyz')
        def my_view(request, tokens):
            return tokens

        mock_sso_redirect.return_value = 'sso_redirect_view_called'

        request = self.factory.get('https://www.example.com/my_view/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        response = my_view(request)
        self.assertEqual(
            response,
            'sso_redirect_view_called'
        )

    def test_coming_back_from_sso(self):
        logger.debug('start')

        @tokens_required(scopes='abc', new=True)
        def my_view(request, tokens):
            return tokens

        request = self.factory.get('https://www.example.com/my_view/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        CallbackRedirect.objects.create(
            session_key=request.session.session_key,
            url='https://www.example.com/redirect/',
            state='xyz',
            token=self.token
        )

        response = my_view(request)
        self.assertEqual(
            response.first(),
            self.token
        )

    def test_user_not_authed(self):
        logger.debug('start')

        @tokens_required(scopes='abc')
        def my_view(request, tokens):
            return tokens

        mock_user = Mock(spec=User)
        mock_user.is_authenticated = False

        request = self.factory.get('https://www.example.com/my_view/')
        request.user = mock_user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        response = my_view(request)
        self.assertEqual(
            response.url,
            redirect_to_login(request.get_full_path()).url
        )


class TestTokenRequired(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            'Bruce Wayne',
            'abc@example.com',
            'password'
        )

        self.token = _store_as_Token(
            _generate_token(
                character_id=99,
                character_name=self.user.username,
                scopes=['abc', '123']
            ),
            self.user
        )
        self.factory = RequestFactory()
        CallbackRedirect.objects.all().delete()

    @patch('esi.views.select_token', autospec=True)
    @patch('esi.views.sso_redirect', autospec=True)
    def test_initial_call_with_matching_tokens(
        self,
        mock_sso_redirect,
        mock_select_token
    ):
        logger.debug('start')

        @token_required(scopes='abc')
        def my_view(request, tokens):
            return tokens

        mock_sso_redirect.return_value = 'sso_redirect_view_called'
        mock_select_token.return_value = 'select_token_view_called'

        request = self.factory.get('https://www.example.com/my_view/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        response = my_view(request)
        self.assertEqual(
            response,
            'select_token_view_called'
        )

    @patch('esi.views.select_token', autospec=True)
    @patch('esi.views.sso_redirect', autospec=True)
    def test_initial_call_wo_matching_tokens(
        self,
        mock_sso_redirect,
        mock_select_token
    ):
        logger.debug('start')

        @token_required(scopes='xyz')
        def my_view(request, tokens):
            return tokens

        mock_sso_redirect.return_value = 'sso_redirect_view_called'
        mock_select_token.return_value = 'select_token_view_called'

        request = self.factory.get('https://www.example.com/my_view/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        response = my_view(request)
        self.assertEqual(
            response,
            'sso_redirect_view_called'
        )

    def test_coming_back_from_sso_normal(
        self,
    ):
        logger.debug('start')

        @token_required(scopes='abc', new=True)
        def my_view(request, token):
            return token

        request = self.factory.get('https://www.example.com/my_view/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        CallbackRedirect.objects.create(
            session_key=request.session.session_key,
            url='https://www.example.com/redirect/',
            state='qwe123',
            token=self.token
        )

        response = my_view(request)
        self.assertEqual(
            response,
            self.token
        )

    @patch('esi.views.select_token', autospec=True)
    @patch('esi.views.sso_redirect', autospec=True)
    def test_user_wants_to_add_new_token(
        self,
        mock_sso_redirect,
        mock_select_token
    ):
        logger.debug('start')

        @token_required(scopes='abc')
        def my_view(request, token):
            return token

        mock_sso_redirect.return_value = 'sso_redirect_view_called'
        mock_select_token.return_value = 'select_token_view_called'

        request = self.factory.post(
            'https://www.example.com/my_view/',
            {
                '_add': False
            }
        )
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        CallbackRedirect.objects.create(
            session_key=request.session.session_key,
            url='https://www.example.com/redirect/',
            state='qwe123',
            token=self.token
        )

        response = my_view(request)
        self.assertEqual(
            response,
            self.token
        )

    @patch('esi.views.select_token', autospec=True)
    @patch('esi.views.sso_redirect', autospec=True)
    def test_user_chose_existing_token(
        self,
        mock_sso_redirect,
        mock_select_token
    ):
        logger.debug('start')

        @token_required(scopes='abc')
        def my_view(request, token):
            return token

        mock_sso_redirect.return_value = 'sso_redirect_view_called'
        mock_select_token.return_value = 'select_token_view_called'

        request = self.factory.post(
            'https://www.example.com/my_view/',
            {
                '_token': self.token.pk
            }
        )
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        CallbackRedirect.objects.create(
            session_key=request.session.session_key,
            url='https://www.example.com/redirect/',
            state='qwe123',
            token=self.token
        )

        response = my_view(request)
        self.assertEqual(
            response,
            self.token
        )

    @patch('esi.views.select_token', autospec=True)
    @patch('esi.views.sso_redirect', autospec=True)
    def test_user_chose_token_which_does_not_exist(
        self,
        mock_sso_redirect,
        mock_select_token
    ):
        logger.debug('start')

        @token_required(scopes='abc')
        def my_view(request, token):
            return token

        mock_sso_redirect.return_value = 'sso_redirect_view_called'
        mock_select_token.return_value = 'select_token_view_called'

        invalid_token_pk = max(int(x.pk) for x in Token.objects.all()) + 1
        request = self.factory.post(
            'https://www.example.com/my_view/',
            {
                '_token': invalid_token_pk
            }
        )
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        response = my_view(request)
        self.assertEqual(
            response,
            'select_token_view_called'
        )


class TestSingleUseTokenRequired(TestCase):

    def setUp(self):
        self.token = _store_as_Token(
            _generate_token(
                character_id=99,
                character_name="No Auth Character",
                scopes=['abc', '123']
            ),
            None
        )
        self.factory = RequestFactory()
        CallbackRedirect.objects.all().delete()

    @patch('esi.views.sso_redirect', autospec=True)
    def test_initial_call_wo_matching_tokens(
        self,
        mock_sso_redirect
    ):
        logger.debug('start')

        @single_use_token(scopes='xyz')
        def my_view(request, tokens):
            return tokens

        mock_sso_redirect.return_value = 'sso_redirect_view_called'

        request = self.factory.get('https://www.example.com/my_view/')
        request.user = None
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        response = my_view(request)
        self.assertEqual(
            response,
            'sso_redirect_view_called'
        )

    def test_coming_back_from_sso_normal(
        self,
    ):
        logger.debug('start')

        @single_use_token(scopes='abc', new=True)
        def my_view(request, token):
            return token

        request = self.factory.get('https://www.example.com/my_view/')
        request.user = None
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        CallbackRedirect.objects.create(
            session_key=request.session.session_key,
            url='https://www.example.com/redirect/',
            state='qwe123',
            token=self.token
        )

        response = my_view(request)
        self.assertEqual(
            response,
            self.token
        )
