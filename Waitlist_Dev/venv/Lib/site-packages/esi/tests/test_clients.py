from datetime import datetime, timedelta, timezone
import os
from unittest.mock import patch, Mock
import json

import bravado
from bravado_core.spec import Spec
from bravado.requests_client import RequestsClient
from bravado.exception import HTTPBadGateway
import requests_mock

import django
from django.contrib.auth.models import User
from django.core.cache import cache

from . import _generate_token, _store_as_Token, NoSocketsTestCase
from .factories import create_http_error
from ..clients import (
    EsiClientProvider,
    esi_client_factory,
    TokenAuthenticator,
    build_cache_name,
    build_spec,
    build_spec_url,
    cache_spec,
    get_spec,
    read_spec,
    minimize_spec,
    SwaggerClient,
    CachingHttpFuture,
    RequestsClientPlus,
)
from ..errors import TokenExpiredError

SWAGGER_SPEC_PATH_MINIMAL = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "test_swagger.json"
)
SWAGGER_SPEC_PATH_FULL = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "test_swagger_full.json"
)

MODULE_PATH = "esi.clients"


def _load_json_file(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class MockResultFuture:
    def __init__(self):
        dt = datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(seconds=60)
        self.headers = {"Expires": dt.strftime("%a, %d %b %Y %H:%M:%S %Z")}
        self.status_code = 200
        self.text = "dummy"


class MockResultPast:
    def __init__(self):
        dt = datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(seconds=60)
        self.headers = {"Expires": dt.strftime("%a, %d %b %Y %H:%M:%S %Z")}


@patch.object(django.core.cache.cache, "set")
@patch.object(django.core.cache.cache, "get")
@patch.object(bravado.http_future.HttpFuture, "result")
class TestClientCache(NoSocketsTestCase):
    @classmethod
    def setUpTestData(cls):
        spec = _load_json_file(SWAGGER_SPEC_PATH_MINIMAL)
        with requests_mock.Mocker() as requests_mocker:
            requests_mocker.register_uri(
                "GET", url="https://esi.evetech.net/_latest/swagger.json", json=spec
            )
            cls.c = esi_client_factory(spec_file=SWAGGER_SPEC_PATH_MINIMAL)

    def setUp(self) -> None:
        cache.clear()

    def test_cache_expire(self, mock_future_result, mock_cache_get, mock_cache_set):
        mock_future_result.return_value = ({"players": 500}, MockResultFuture())
        mock_cache_get.return_value = False

        # hit api
        r = self.c.Status.get_status().result()
        self.assertEqual(r["players"], 500)

        mock_cache_get.return_value = ({"players": 50}, MockResultFuture())
        # hit cache and pass
        r = self.c.Status.get_status().result()
        self.assertEqual(r["players"], 50)

        mock_cache_get.return_value = ({"players": 50}, MockResultPast())
        # hit cache fail, re-hit api
        r = self.c.Status.get_status().result()
        self.assertEqual(r["players"], 500)

    def test_should_use_cache(self, mock_future_result, mock_cache_get, mock_cache_set):
        # given
        mock_future_result.return_value = ({"players": 500}, MockResultFuture())
        mock_cache_get.return_value = False

        # when
        r = self.c.Status.get_status().result()
        # then
        self.assertEqual(r["players"], 500)
        self.assertTrue(mock_cache_get.called)
        self.assertTrue(mock_cache_set.called)

    def test_should_not_use_cache(
        self, mock_future_result, mock_cache_get, mock_cache_set
    ):
        # given
        mock_future_result.return_value = ({"players": 500}, MockResultFuture())
        mock_cache_get.return_value = False

        # when
        r = self.c.Status.get_status().result(ignore_cache=True)
        # then
        self.assertEqual(r["players"], 500)
        self.assertFalse(mock_cache_get.called)
        self.assertFalse(mock_cache_set.called)

    def test_can_handle_exception_from_cache_set(
        self, mock_future_result, mock_cache_get, mock_cache_set
    ):
        mock_future_result.return_value = ({"players": 500}, MockResultFuture())
        mock_cache_get.return_value = False
        mock_cache_set.side_effect = RuntimeError("TEST: Could not write to cache")

        # hit api
        r = self.c.Status.get_status().result()
        self.assertEqual(r["players"], 500)

    def test_can_handle_exception_from_cache_get(
        self, mock_future_result, mock_cache_get, mock_cache_set
    ):
        mock_future_result.return_value = ({"players": 500}, MockResultFuture())
        mock_cache_get.side_effect = RuntimeError("TEST: Could not read from cache")

        # hit api
        r = self.c.Status.get_status().result()
        self.assertEqual(r["players"], 500)


@patch(MODULE_PATH + ".app_settings.ESI_SPEC_CACHE_DURATION", 3)
@patch(MODULE_PATH + ".app_settings.ESI_API_URL", "https://www.example.com/esi/")
@patch(MODULE_PATH + ".app_settings.ESI_API_DATASOURCE", "dummy")
@patch("esi.models.app_settings.ESI_TOKEN_VALID_DURATION", 120)
class TestTokenAuthenticator(NoSocketsTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "Bruce Wayne", "abc@example.com", "password"
        )
        self.token = _store_as_Token(
            _generate_token(
                character_id=101,
                character_name=self.user.username,
                scopes=["abc"],
                access_token="my_access_token",
            ),
            self.user,
        )

    def test_apply_defaults(self):
        request = Mock()
        request.headers = dict()
        request.params = dict()

        x = TokenAuthenticator()
        request2 = x.apply(request)
        self.assertEqual(request2.headers["Authorization"], None)
        self.assertEqual(request2.params["datasource"], "dummy")

    def test_apply_token(self):
        request = Mock()
        request.headers = dict()
        request.params = dict()

        x = TokenAuthenticator(token=self.token)
        request2 = x.apply(request)
        self.assertEqual(request2.headers["Authorization"], "Bearer my_access_token")
        self.assertEqual(request2.params["datasource"], "dummy")

    def test_apply_token_datasource(self):
        request = Mock()
        request.headers = dict()
        request.params = dict()

        x = TokenAuthenticator(token=self.token, datasource="dummy2")
        request2 = x.apply(request)
        self.assertEqual(request2.headers["Authorization"], "Bearer my_access_token")
        self.assertEqual(request2.params["datasource"], "dummy2")

    @patch("esi.models.Token.refresh", spec=True)
    def test_apply_token_expired_success(self, mock_Token_refresh):
        request = Mock()
        request.headers = dict()
        request.params = dict()

        self.token.created -= timedelta(121)

        x = TokenAuthenticator(token=self.token)
        request2 = x.apply(request)
        self.assertEqual(request2.headers["Authorization"], "Bearer my_access_token")
        self.assertEqual(request2.params["datasource"], "dummy")
        self.assertEqual(mock_Token_refresh.call_count, 1)

    @patch("esi.models.Token.refresh", spec=True)
    def test_apply_token_expired_failed(self, mock_Token_refresh):
        request = Mock()
        request.headers = dict()
        request.params = dict()

        self.token.created -= timedelta(121)
        self.token.refresh_token = None

        x = TokenAuthenticator(token=self.token)
        with self.assertRaises(TokenExpiredError):
            x.apply(request)

        self.assertEqual(mock_Token_refresh.call_count, 0)


class TestModuleFunctions(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.spec = _load_json_file(SWAGGER_SPEC_PATH_MINIMAL)

    def test_build_cache_name(self):
        self.assertEqual(build_cache_name("abc"), "esi_swaggerspec_abc")

    @patch(MODULE_PATH + ".app_settings.ESI_SPEC_CACHE_DURATION", 3)
    def test_cache_spec(self):
        spec = {"dummy_spec": True}
        cache_spec("abc", spec)
        self.assertDictEqual(cache.get("esi_swaggerspec_abc"), spec)

    @patch(MODULE_PATH + ".app_settings.ESI_API_URL", "https://www.example.com/esi/")
    def test_build_spec_url(self):
        self.assertEqual(
            build_spec_url("v2"), "https://www.example.com/esi/v2/swagger.json"
        )

    @requests_mock.Mocker()
    @patch(MODULE_PATH + ".app_settings.ESI_SPEC_CACHE_DURATION", 1)
    def test_get_spec_defaults(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec
        )
        # when
        spec = get_spec("latest")
        # then
        self.assertIsInstance(spec, Spec)

    @patch(MODULE_PATH + ".app_settings.ESI_SPEC_CACHE_DURATION", 1)
    def test_get_spec_with_http_client(self):
        mock_http_client = Mock(spec=RequestsClient)
        mock_http_client.request.return_value.result.return_value.json.return_value = (
            self.spec
        )
        spec = get_spec("latest", http_client=mock_http_client)
        self.assertIsInstance(spec, Spec)

    @patch(MODULE_PATH + ".app_settings.ESI_SPEC_CACHE_DURATION", 1)
    def test_get_spec_with_config(self):
        mock_http_client = Mock(spec=RequestsClient)
        mock_http_client.request.return_value.result.return_value.json.return_value = (
            self.spec
        )
        spec = get_spec(
            "latest", http_client=mock_http_client, config={"dummy_config": True}
        )
        self.assertIsInstance(spec, Spec)
        self.assertIn("dummy_config", spec.config)

    @patch(MODULE_PATH + ".app_settings.ESI_SPEC_CACHE_DURATION", 1)
    def test_build_spec_defaults(self):
        mock_http_client = Mock(spec=RequestsClient)
        mock_http_client.request.return_value.result.return_value.json.return_value = (
            self.spec
        )
        spec = build_spec("v1", http_client=mock_http_client)
        self.assertIsInstance(spec, Spec)

    @patch(MODULE_PATH + ".app_settings.ESI_SPEC_CACHE_DURATION", 1)
    def test_build_spec_explicit_resource_found(self):
        mock_http_client = Mock(spec=RequestsClient)
        mock_http_client.request.return_value.result.return_value.json.return_value = (
            self.spec
        )
        spec = build_spec("v1", http_client=mock_http_client, Status="v1")
        self.assertIsInstance(spec, Spec)

    @patch(MODULE_PATH + ".app_settings.ESI_SPEC_CACHE_DURATION", 1)
    def test_build_spec_explicit_resource_not_found(self):
        mock_http_client = Mock(spec=RequestsClient)
        mock_http_client.request.return_value.result.return_value.json.return_value = (
            self.spec
        )
        with self.assertRaises(AttributeError):
            build_spec("v1", http_client=mock_http_client, Character="v4")

    @requests_mock.Mocker()
    def test_read_spec(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        # when
        client = read_spec(SWAGGER_SPEC_PATH_MINIMAL)
        # then
        self.assertIsInstance(client, SwaggerClient)

    def test_minimize_spec_defaults(self):
        spec_dict = minimize_spec(self.spec)
        self.assertIsInstance(spec_dict, dict)
        # todo: add better verification of functionality

    def test_minimize_spec_resources(self):
        spec_dict = minimize_spec(self.spec, resources=["Status"])
        self.assertIsInstance(spec_dict, dict)
        # todo: add better verification of functionality


@patch(MODULE_PATH + ".app_settings.ESI_SPEC_CACHE_DURATION", 1)
@requests_mock.Mocker()
class TestEsiClientFactory(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.spec = _load_json_file(SWAGGER_SPEC_PATH_MINIMAL)

    def setUp(self):
        self.user = User.objects.create_user(
            "Bruce Wayne", "abc@example.com", "password"
        )
        self.token = _store_as_Token(
            _generate_token(
                character_id=101,
                character_name=self.user.username,
                scopes=["abc"],
                access_token="my_access_token",
            ),
            self.user,
        )

    def test_minimal_client(self, requests_mocker):
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec
        )
        # when
        client = esi_client_factory()
        # then
        self.assertIsInstance(client, SwaggerClient)

    def test_client_with_token(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec
        )
        # when
        client = esi_client_factory(token=self.token)
        # then
        self.assertIsInstance(client, SwaggerClient)

    def test_client_with_version(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec
        )
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/v1/swagger.json", json=self.spec
        )
        # when
        client = esi_client_factory(version="v1")
        # then
        self.assertIsInstance(client, SwaggerClient)

    def test_client_with_spec_file(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec
        )
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        # when
        client = esi_client_factory(spec_file=SWAGGER_SPEC_PATH_MINIMAL)
        # then
        self.assertIsInstance(client, SwaggerClient)

    def test_client_with_explicit_resource(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec
        )
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/v1/swagger.json", json=self.spec
        )
        # when
        client = esi_client_factory(Status="v1")
        # then
        self.assertIsInstance(client, SwaggerClient)

    def test__time_to_expiry_failure(self, requests_mocker):
        seconds = CachingHttpFuture._time_to_expiry("fail")
        self.assertEqual(seconds, 0)


@patch(MODULE_PATH + ".HttpFuture.result")
class TestClientResult(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        spec = _load_json_file(SWAGGER_SPEC_PATH_MINIMAL)
        with requests_mock.Mocker() as requests_mocker:
            requests_mocker.register_uri(
                "GET", url="https://esi.evetech.net/_latest/swagger.json", json=spec
            )
            cls.esi_client = esi_client_factory(spec_file=SWAGGER_SPEC_PATH_MINIMAL)

    @patch(MODULE_PATH + ".app_settings.ESI_REQUESTS_CONNECT_TIMEOUT", 10)
    @patch(MODULE_PATH + ".app_settings.ESI_REQUESTS_READ_TIMEOUT", 60)
    def test_use_default_timeout(self, mock_future_result):
        # given
        mock_future_result.return_value = (None, Mock(**{"headers": {}}))
        # when
        self.esi_client.Status.get_status().result()
        # then
        self.assertTrue(mock_future_result.called)
        _, kwargs = mock_future_result.call_args
        self.assertEqual(kwargs["timeout"], (10, 60))

    @patch(MODULE_PATH + ".app_settings.ESI_REQUESTS_CONNECT_TIMEOUT", 10)
    @patch(MODULE_PATH + ".app_settings.ESI_REQUESTS_READ_TIMEOUT", 60)
    def test_use_custom_timeout(self, mock_future_result):
        # given
        mock_future_result.return_value = (None, Mock(**{"headers": {}}))
        # when
        self.esi_client.Status.get_status().result(timeout=42)
        # then
        self.assertTrue(mock_future_result.called)
        _, kwargs = mock_future_result.call_args
        self.assertEqual(kwargs["timeout"], 42)

    def test_support_language_parameter(self, mock_future_result):
        # given
        mock_future_result.return_value = (None, Mock(**{"headers": {}}))
        my_language = "de"
        operation = self.esi_client.Status.get_status()
        # when
        operation.result(language=my_language)
        # then
        self.assertTrue(mock_future_result.called)
        self.assertEqual(operation.future.request.params["language"], my_language)
        _, kwargs = mock_future_result.call_args
        self.assertNotIn("language", kwargs)

    @patch(MODULE_PATH + ".app_settings.ESI_SERVER_ERROR_BACKOFF_FACTOR", 0.5)
    @patch(MODULE_PATH + ".app_settings.ESI_SERVER_ERROR_MAX_RETRIES", 3)
    @patch(MODULE_PATH + ".sleep", wraps=lambda x: None)
    def test_retries_1(self, mock_sleep, mock_future_result):
        mock_future_result.side_effect = create_http_error(502)
        try:
            self.esi_client.Status.get_status().result()
        except HTTPBadGateway as e:
            # requests error thrown
            self.assertIsInstance(e, HTTPBadGateway)
            # we tried # times before raising
            self.assertEqual(mock_future_result.call_count, 4)
            call_list = mock_sleep.call_args_list
            result = [args[0] for args, _ in [x for x in call_list]]
            expected = [0.5, 1.0, 2.0]
            self.assertListEqual(expected, result)

    @patch(MODULE_PATH + ".app_settings.ESI_SERVER_ERROR_BACKOFF_FACTOR", 0.5)
    @patch(MODULE_PATH + ".app_settings.ESI_SERVER_ERROR_MAX_RETRIES", 1)
    @patch(MODULE_PATH + ".sleep", lambda x: None)
    def test_retries_2(self, mock_future_result):
        mock_future_result.side_effect = create_http_error(502)
        try:
            self.esi_client.Status.get_status().result()
        except HTTPBadGateway as e:
            # requests error thrown
            self.assertIsInstance(e, HTTPBadGateway)
            # we tried # times before raising
            self.assertEqual(mock_future_result.call_count, 2)

    @patch(MODULE_PATH + ".app_settings.ESI_SERVER_ERROR_BACKOFF_FACTOR", 0.5)
    @patch(MODULE_PATH + ".app_settings.ESI_SERVER_ERROR_MAX_RETRIES", 0)
    @patch(MODULE_PATH + ".sleep", lambda x: None)
    def test_retries_3(self, mock_future_result):
        mock_future_result.side_effect = create_http_error(502)
        try:
            self.esi_client.Status.get_status().result()
        except HTTPBadGateway as e:
            # requests error thrown
            self.assertIsInstance(e, HTTPBadGateway)
            # we tried # times before raising
            self.assertEqual(mock_future_result.call_count, 1)

    @patch(MODULE_PATH + ".app_settings.ESI_SERVER_ERROR_BACKOFF_FACTOR", 0.5)
    @patch(MODULE_PATH + ".app_settings.ESI_SERVER_ERROR_MAX_RETRIES", 4)
    @patch(MODULE_PATH + ".sleep", lambda x: None)
    def test_retry_with_custom_retries(self, mock_future_result):
        mock_future_result.side_effect = create_http_error(502)
        try:
            self.esi_client.Status.get_status().result(retries=1)
        except HTTPBadGateway as e:
            # requests error thrown
            self.assertIsInstance(e, HTTPBadGateway)
            # we tried # times before raising
            self.assertEqual(mock_future_result.call_count, 2)


@patch(MODULE_PATH + ".HttpFuture.result")
class TestClientResultAllPages(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        spec = _load_json_file(SWAGGER_SPEC_PATH_FULL)
        with requests_mock.Mocker() as requests_mocker:
            requests_mocker.register_uri(
                "GET", url="https://esi.evetech.net/_latest/swagger.json", json=spec
            )
            cls.esi_client = esi_client_factory(spec_file=SWAGGER_SPEC_PATH_FULL)

    def test_pages(self, mock_future_result):
        class MockResultHeaders:
            def __init__(self):
                self.headers = {"X-Pages": 10}
                self.status_code = 200
                self.text = "dummy"

        # given
        mock_future_result.return_value = ({"contract_test": 1}, MockResultHeaders())
        self.esi_client.Contracts.get_contracts_public_region_id(region_id=1).results()
        # then
        self.assertEqual(mock_future_result.call_count, 10)  # we got 10 pages of data

    def test_pages_response(self, mock_future_result):
        class MockResultHeaders:
            def __init__(self):
                self.headers = {"X-Pages": 10}
                self.status_code = 200
                self.text = "dummy"

        # given
        mock_future_result.return_value = ({"contract_test": 1}, MockResultHeaders())
        o = self.esi_client.Contracts.get_contracts_public_region_id(region_id=1)
        o.request_config.also_return_response = True
        # when
        result, response = o.results()
        # then
        self.assertEqual(mock_future_result.call_count, 10)  # we got 10 pages of data
        self.assertEqual(len(result), 10)  # we got 10 lots of data
        self.assertEqual(response.headers, {"X-Pages": 10})  # we got header of data

    def test_pages_on_non_paged_endpoint(self, mock_future_result):
        class MockResultHeaders:
            def __init__(self):
                self.headers = {"header_test": "ok"}
                self.status_code = 200
                self.text = "dummy"

        # given
        mock_future_result.return_value = ({"status_test": 1}, MockResultHeaders())
        # when
        self.esi_client.Status.get_status().results()
        # then
        self.assertEqual(mock_future_result.call_count, 1)  # we got no pages of data


@patch(MODULE_PATH + ".app_settings.ESI_LANGUAGES", ["lang1", "lang2", "lang3"])
@patch(MODULE_PATH + ".CachingHttpFuture.results", spec=True)
@requests_mock.Mocker()
class TestClientResultsLocalized(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.spec = _load_json_file(SWAGGER_SPEC_PATH_MINIMAL)

    @staticmethod
    def my_results(**kwargs):
        if "language" in kwargs:
            return "response_" + kwargs["language"]
        return ""

    def test_default(self, mock_future_results, requests_mocker):
        # given
        mock_future_results.side_effect = self.my_results
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        client = esi_client_factory(spec_file=SWAGGER_SPEC_PATH_MINIMAL)
        # when
        result = client.Status.get_status().results_localized()
        # then
        expected = {
            "lang1": "response_lang1",
            "lang2": "response_lang2",
            "lang3": "response_lang3",
        }
        self.assertDictEqual(result, expected)

    def test_custom_languages(self, mock_future_results, requests_mocker):
        # given
        mock_future_results.side_effect = self.my_results
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        client = esi_client_factory(spec_file=SWAGGER_SPEC_PATH_MINIMAL)
        # when
        result = client.Status.get_status().results_localized(
            languages=["lang2", "lang3"]
        )
        # then
        expected = {
            "lang2": "response_lang2",
            "lang3": "response_lang3",
        }
        self.assertDictEqual(result, expected)

    def test_raise_on_invalid_language(self, mock_future_results, requests_mocker):
        # given
        mock_future_results.side_effect = self.my_results
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        client = esi_client_factory(spec_file=SWAGGER_SPEC_PATH_MINIMAL)
        # when/then
        with self.assertRaises(ValueError):
            client.Status.get_status().results_localized(languages=["lang2", "xxx"])


@requests_mock.Mocker()
class TestEsiClientProvider(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.spec = _load_json_file(SWAGGER_SPEC_PATH_MINIMAL)

    def test_client_loads_on_demand(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec
        )
        my_provider = EsiClientProvider()
        # when
        esi_client = my_provider.client
        # then
        self.assertIsInstance(esi_client, SwaggerClient)
        self.assertIsInstance(my_provider, EsiClientProvider)
        self.assertIsInstance(my_provider.client, SwaggerClient)
        self.assertEqual(str(my_provider), "EsiClientProvider")

    # FIXME: This test currently fails sometimes when run with tox.
    # def test_with_version(self, requests_mocker):
    #     # given
    #     requests_mocker.register_uri(
    #         "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
    #     )
    #     requests_mocker.register_uri(
    #         "GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec
    #     )
    #     requests_mocker.register_uri(
    #         "GET", url="https://esi.evetech.net/v1/swagger.json", json=self.spec
    #     )
    #     my_provider = EsiClientProvider(version="v1")
    #     # when
    #     esi_client = my_provider.client
    #     # then
    #     self.assertIsInstance(esi_client, SwaggerClient)
    #     urls_callled = [x.url for x in requests_mocker.request_history]
    #     self.assertIn("https://esi.evetech.net/v1/swagger.json", urls_callled)

    def test_with_spec_file(self, requests_mocker):
        # given
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec
        )
        requests_mocker.register_uri(
            "GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec
        )
        my_provider = EsiClientProvider(spec_file=SWAGGER_SPEC_PATH_MINIMAL)
        # when
        esi_client = my_provider.client
        # then
        self.assertIsInstance(esi_client, SwaggerClient)


@requests_mock.Mocker()
class TestClientResult2(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        spec = _load_json_file(SWAGGER_SPEC_PATH_MINIMAL)
        with patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", "email@example.com"), patch(
            MODULE_PATH + ".__title__", "Django-ESI"
        ), patch(MODULE_PATH + ".__version__", "1.0.0"):
            with requests_mock.Mocker() as requests_mocker:
                requests_mocker.register_uri(
                    "GET", url="https://esi.evetech.net/_latest/swagger.json", json=spec
                )
                cls.esi_client = esi_client_factory(spec_file=SWAGGER_SPEC_PATH_MINIMAL)

    def test_normal_call(self, requests_mocker):
        # given
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/")
        # when
        self.esi_client.Status.get_status().result()
        # then
        self.assertTrue(requests_mocker.called)
        request = requests_mocker.last_request
        self.assertEqual(request._request.headers["User-Agent"], "Django-ESI/1.0.0 (email@example.com; +https://gitlab.com/allianceauth/django-esi)")

    def test_existing_headers(self, requests_mocker):
        # given
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/")
        # when
        self.esi_client.Status.get_status().result()
        # then
        self.assertTrue(requests_mocker.called)
        request = requests_mocker.last_request
        self.assertEqual(request._request.headers["User-Agent"], "Django-ESI/1.0.0 (email@example.com; +https://gitlab.com/allianceauth/django-esi)")


class TestRequestsClientPlus(NoSocketsTestCase):
    def test_single_header(self):
        """When no headers are set, just add the new header"""
        obj = RequestsClientPlus()
        obj.user_agent = "abc"
        result = obj.request(
            {"method": "GET", "url": "https://esi.evetech.net/v1/status/"}
        )
        self.assertEqual(result.future.request.headers["User-Agent"], "abc")

    def test_existing_header(self):
        """When a header exists, leave it intact"""
        obj = RequestsClientPlus()
        obj.user_agent = "abc"
        result = obj.request(
            {
                "method": "GET",
                "url": "https://esi.evetech.net/v1/status/",
                "headers": {"From": "email@example.com"},
            }
        )
        self.assertEqual(result.future.request.headers["User-Agent"], "abc")
        self.assertEqual(result.future.request.headers["From"], "email@example.com")

    def test_no_user_agent(self):
        """When no user agent is defined, leave the existing header intact"""
        obj = RequestsClientPlus()
        result = obj.request(
            {
                "method": "GET",
                "url": "https://esi.evetech.net/v1/status/",
                "headers": {"From": "email@example.com"},
            }
        )
        self.assertEqual(result.future.request.headers["From"], "email@example.com")
        self.assertNotIn("User-Agent", result.future.request.headers)


@patch(MODULE_PATH + ".__title__", "Django-ESI")
@patch(MODULE_PATH + ".__version__", "1.0.0")
@requests_mock.Mocker()
class TestEsiClientFactoryAppText(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.spec = _load_json_file(SWAGGER_SPEC_PATH_MINIMAL)
        cls.status_response = {
            "players": 12345,
            "server_version": "1132976",
            "start_time": "2017-01-02T12:34:56Z",
        }

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", None)
    def test_defaults(self, requests_mocker) -> None:
        # This test is not expected to hit given that ESI_USER_CONTACT_EMAIL must be set
        # But here it is for completeness
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = esi_client_factory()
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "Django-ESI/1.0.0 (None; +https://gitlab.com/allianceauth/django-esi)")

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", "email@example.com")
    def test_defaults_email(self, requests_mocker) -> None:
        # given
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = esi_client_factory()
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "Django-ESI/1.0.0 (email@example.com; +https://gitlab.com/allianceauth/django-esi)")

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", None)
    def test_app_text(self, requests_mocker) -> None:
        # Deprecated
        # This test is not expected to hit given that ESI_USER_CONTACT_EMAIL must be set
        # given
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = esi_client_factory(app_info_text="my-app v1.0.0")
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "my-app v1.0.0 (None) Django-ESI/1.0.0 (+https://gitlab.com/allianceauth/django-esi)",)

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", "email@example.com")
    def test_app_text_with_email(self, requests_mocker):
        # Deprecated
        # given
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = esi_client_factory(app_info_text="my-app v1.0.0")
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "my-app v1.0.0 (email@example.com) Django-ESI/1.0.0 (+https://gitlab.com/allianceauth/django-esi)",)

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", "email@example.com")
    def test_ua_generator(self, requests_mocker):
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = esi_client_factory(ua_appname="MyApp", ua_version="1.0.0")
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "MyApp/1.0.0 (email@example.com) Django-ESI/1.0.0 (+https://gitlab.com/allianceauth/django-esi)")

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", "email@example.com")
    def test_ua_generator_with_url(self, requests_mocker):
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = esi_client_factory(ua_appname="MyApp", ua_version="1.0.0", ua_url="https://example.com")
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "MyApp/1.0.0 (email@example.com; +https://example.com) Django-ESI/1.0.0 (+https://gitlab.com/allianceauth/django-esi)")

@patch(MODULE_PATH + ".__title__", "Django-ESI")
@patch(MODULE_PATH + ".__version__", "1.0.0")
@requests_mock.Mocker()
class TestEsiClientProviderAppText(NoSocketsTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.spec = _load_json_file(SWAGGER_SPEC_PATH_MINIMAL)
        cls.status_response = {
            "players": 12345,
            "server_version": "1132976",
            "start_time": "2017-01-02T12:34:56Z",
        }

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", None)
    def test_defaults(self, requests_mocker) -> None:
        # This test is not expected to hit given that ESI_USER_CONTACT_EMAIL must be set
        # But here it is for completeness
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = EsiClientProvider().client
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "Django-ESI/1.0.0 (None; +https://gitlab.com/allianceauth/django-esi)")

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", "email@example.com")
    def test_defaults_email(self, requests_mocker) -> None:
        # given
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = EsiClientProvider().client
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "Django-ESI/1.0.0 (email@example.com; +https://gitlab.com/allianceauth/django-esi)")

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", None)
    def test_app_text(self, requests_mocker) -> None:
        # Deprecated
        # This test is not expected to hit given that ESI_USER_CONTACT_EMAIL must be set
        # given
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = EsiClientProvider(app_info_text="my-app v1.0.0").client
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "my-app v1.0.0 (None) Django-ESI/1.0.0 (+https://gitlab.com/allianceauth/django-esi)",)

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", "email@example.com")
    def test_app_text_with_email(self, requests_mocker):
        # Deprecated
        # given
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = EsiClientProvider(app_info_text="my-app v1.0.0").client
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "my-app v1.0.0 (email@example.com) Django-ESI/1.0.0 (+https://gitlab.com/allianceauth/django-esi)",)

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", "email@example.com")
    def test_ua_generator(self, requests_mocker):
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = EsiClientProvider(ua_appname="MyApp", ua_version="1.0.0").client
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "MyApp/1.0.0 (email@example.com) Django-ESI/1.0.0 (+https://gitlab.com/allianceauth/django-esi)")

    @patch(MODULE_PATH + ".app_settings.ESI_USER_CONTACT_EMAIL", "email@example.com")
    def test_ua_generator_with_url(self, requests_mocker):
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/_latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/latest/swagger.json", json=self.spec)
        requests_mocker.register_uri("GET", url="https://esi.evetech.net/v1/status/", json=self.status_response)
        client = EsiClientProvider(ua_appname="MyApp", ua_version="1.0.0", ua_url="https://example.com").client
        # when
        operation = client.Status.get_status()
        # then
        self.assertEqual(operation.future.request.headers["User-Agent"], "MyApp/1.0.0 (email@example.com; +https://example.com) Django-ESI/1.0.0 (+https://gitlab.com/allianceauth/django-esi)")
