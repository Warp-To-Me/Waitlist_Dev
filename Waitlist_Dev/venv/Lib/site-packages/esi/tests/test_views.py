from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import (
    HttpResponse,
    HttpResponseRedirect,
    Http404,
    HttpResponseBadRequest
)
from django.test import TestCase, RequestFactory

from . import _generate_token, _store_as_Token
from ..models import CallbackRedirect
from ..views import sso_redirect, receive_callback, select_token


ESI_SSO_CLIENT_ID = 'abc'
ESI_SSO_CALLBACK_URL = 'https://www.example.com/callback/'
ESI_OAUTH_LOGIN_URL = 'https://www.example.com/oauth/'

redirect_sub_url = '/%s/' % ('x' * (2048 - 25))
redirect_url = 'https://www.example.com' + redirect_sub_url


class TestSsoCallbackView(TestCase):

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

    @patch('esi.views.app_settings.ESI_SSO_CLIENT_ID', ESI_SSO_CLIENT_ID)
    @patch('esi.views.app_settings.ESI_SSO_CALLBACK_URL', ESI_SSO_CALLBACK_URL)
    @patch('esi.views.app_settings.ESI_OAUTH_LOGIN_URL', ESI_OAUTH_LOGIN_URL)
    @patch('esi.views.OAuth2Session', autospec=True)
    def test_redirect_to_url_no_scopes(self, mock_OAuth2Session):
        state = 'my_awesome_state'
        mock_OAuth2Session.return_value.authorization_url.return_value = \
            (redirect_url, state)

        request = self.factory.get(redirect_url)
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        http_response = sso_redirect(request)

        self.assertTrue(mock_OAuth2Session.called)
        args, kwargs = mock_OAuth2Session.call_args
        self.assertEqual(kwargs['scope'], [])

        self.assertEqual(http_response.url, redirect_url)

        callback_redirects = (
            CallbackRedirect.objects.filter(session_key=request.session.session_key)
        )
        self.assertEqual(len(callback_redirects), 1)
        callback_redirect = callback_redirects.first()
        self.assertEqual(callback_redirect.url, redirect_sub_url)
        self.assertEqual(callback_redirect.session_key, request.session.session_key)
        self.assertEqual(callback_redirect.state, state)

    @patch('esi.views.app_settings.ESI_SSO_CLIENT_ID', ESI_SSO_CLIENT_ID)
    @patch('esi.views.app_settings.ESI_SSO_CALLBACK_URL', ESI_SSO_CALLBACK_URL)
    @patch('esi.views.app_settings.ESI_OAUTH_LOGIN_URL', ESI_OAUTH_LOGIN_URL)
    @patch('esi.views.OAuth2Session', autospec=True)
    def test_redirect_to_url_w_single_scope(self, mock_OAuth2Session):
        state = 'my_awesome_state'
        mock_OAuth2Session.return_value.authorization_url.return_value = \
            (redirect_url, state)

        request = self.factory.get(redirect_url)
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        http_response = sso_redirect(request, scopes='abc')
        self.assertTrue(mock_OAuth2Session.called)
        args, kwargs = mock_OAuth2Session.call_args
        self.assertEqual(kwargs['scope'], ['abc'])

        self.assertEqual(http_response.url, redirect_url)

        callback_redirects = (
            CallbackRedirect.objects.filter(session_key=request.session.session_key)
        )
        self.assertEqual(len(callback_redirects), 1)
        callback_redirect = callback_redirects.first()
        self.assertEqual(callback_redirect.url, redirect_sub_url)
        self.assertEqual(callback_redirect.session_key, request.session.session_key)
        self.assertEqual(callback_redirect.state, state)

    @patch('esi.views.app_settings.ESI_SSO_CLIENT_ID', ESI_SSO_CLIENT_ID)
    @patch('esi.views.app_settings.ESI_SSO_CALLBACK_URL', ESI_SSO_CALLBACK_URL)
    @patch('esi.views.app_settings.ESI_OAUTH_LOGIN_URL', ESI_OAUTH_LOGIN_URL)
    @patch('esi.views.OAuth2Session', autospec=True)
    def test_redirect_to_url_w_multiple_scopes(self, mock_OAuth2Session):
        state = 'my_awesome_state'
        mock_OAuth2Session.return_value.authorization_url.return_value = \
            (redirect_url, state)

        request = self.factory.get(redirect_url)
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        http_response = sso_redirect(request, scopes=['abc', 'def'])
        self.assertTrue(mock_OAuth2Session.called)
        args, kwargs = mock_OAuth2Session.call_args
        self.assertEqual(kwargs['scope'], ['abc', 'def'])

        self.assertEqual(http_response.url, redirect_url)

        callback_redirects = CallbackRedirect.objects\
            .filter(session_key=request.session.session_key)
        self.assertEqual(len(callback_redirects), 1)
        callback_redirect = callback_redirects.first()
        self.assertEqual(callback_redirect.url, redirect_sub_url)
        self.assertEqual(callback_redirect.session_key, request.session.session_key)
        self.assertEqual(callback_redirect.state, state)

    @patch('esi.views.app_settings.ESI_SSO_CLIENT_ID', ESI_SSO_CLIENT_ID)
    @patch('esi.views.app_settings.ESI_SSO_CALLBACK_URL', ESI_SSO_CALLBACK_URL)
    @patch('esi.views.app_settings.ESI_OAUTH_LOGIN_URL', ESI_OAUTH_LOGIN_URL)
    @patch('esi.views.reverse', autospec=True)
    @patch('esi.views.OAuth2Session', autospec=True)
    def test_redirect_to_view_no_scopes(self, mock_OAuth2Session, mock_reverse):
        state = 'my_awesome_state'
        mock_OAuth2Session.return_value.authorization_url.return_value = \
            (redirect_url, state)
        my_view_url = '/my_view/'
        mock_reverse.return_value = my_view_url

        request = self.factory.get('https://www.example.com/callback2/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        http_response = sso_redirect(request, return_to='my_view')

        self.assertTrue(mock_OAuth2Session.called)
        args, kwargs = mock_OAuth2Session.call_args
        self.assertEqual(kwargs['scope'], [])

        self.assertEqual(http_response.url, redirect_url)

        callback_redirects = (
            CallbackRedirect.objects.filter(session_key=request.session.session_key)
        )
        self.assertEqual(len(callback_redirects), 1)
        callback_redirect = callback_redirects.first()
        self.assertEqual(callback_redirect.url, my_view_url)
        self.assertEqual(callback_redirect.session_key, request.session.session_key)
        self.assertEqual(callback_redirect.state, state)

    @patch('esi.views.app_settings.ESI_SSO_CLIENT_ID', ESI_SSO_CLIENT_ID)
    @patch('esi.views.app_settings.ESI_SSO_CALLBACK_URL', ESI_SSO_CALLBACK_URL)
    @patch('esi.views.reverse')
    def test_sso_redirect_return_to(self, mock_reverse):
        mock_reverse.return_value = '/callback3/'

        request = self.factory.get('https://www.example.com/callback2/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        sso_redirect(request, return_to='callback3')

        callback_redirects = (
            CallbackRedirect.objects.filter(session_key=request.session.session_key)
        )
        self.assertEqual(len(callback_redirects), 1)
        callback_redirect = callback_redirects.first()
        self.assertEqual(callback_redirect.url, '/callback3/')
        self.assertEqual(callback_redirect.session_key, request.session.session_key)

    @patch('esi.views.app_settings.ESI_SSO_CLIENT_ID', ESI_SSO_CLIENT_ID)
    @patch('esi.views.app_settings.ESI_SSO_CALLBACK_URL', ESI_SSO_CALLBACK_URL)
    def test_sso_redirect_start_session(self):
        request = self.factory.get('https://www.example.com/callback2/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)

        sso_redirect(request)

        callback_redirects = (
            CallbackRedirect.objects.filter(session_key=request.session.session_key)
        )
        self.assertEqual(len(callback_redirects), 1)
        callback_redirect = callback_redirects.first()
        self.assertEqual(callback_redirect.url, '/callback2/')
        self.assertEqual(callback_redirect.session_key, request.session.session_key)


class TesReceiveCallbackView(TestCase):

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

    @patch('esi.managers.TokenManager.create_from_request')
    def test_normal(self, mock_create_from_request):
        mock_create_from_request.return_value = self.token

        request = self.factory.get('https://www.example.com?code=abc&state=123')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        callback_redirect = CallbackRedirect.objects.create(
            session_key=request.session.session_key,
            state='123',
            url=redirect_url
        )
        http_response = receive_callback(request)
        callback_redirect.refresh_from_db()
        self.assertIsInstance(http_response, HttpResponseRedirect)
        self.assertEqual(http_response.url, redirect_url)
        self.assertEqual(callback_redirect.token, self.token)

    def test_missing_code(self):
        request = self.factory.get('https://www.example.com?state=123')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        http_response = receive_callback(request)
        self.assertIsInstance(http_response, HttpResponseBadRequest)

    def test_missing_state(self):
        request = self.factory.get('https://www.example.com?code=abc')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        http_response = receive_callback(request)
        self.assertIsInstance(http_response, HttpResponseBadRequest)

    def test_missing_callback(self):
        request = self.factory.get('https://www.example.com?code=abc&state=123')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()

        with self.assertRaises(Http404):
            receive_callback(request)


class TestSelectTokenView(TestCase):
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

    def test_should_render_select_page_on_first_call(self):
        # given
        request = self.factory.get('https://www.example.com/my_view/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()
        # when
        response = select_token(request, scopes='abc')
        # then
        self.assertIn("ESI Token Selection", response.content.decode("utf-8"))

    def test_should_render_select_page_on_second_call(self):
        # given
        request = self.factory.get('https://www.example.com/my_view/')
        request.user = self.user
        middleware = SessionMiddleware(HttpResponse)
        middleware.process_request(request)
        request.session.save()
        CallbackRedirect.objects.create(
            session_key=request.session.session_key,
            state='state123',
            token=self.token
        )
        # when
        response = select_token(request, scopes='abc', new=True)
        # then
        self.assertIn("ESI Token Selection", response.content.decode("utf-8"))
