import socket
from django.test import TestCase


def _dt_eveformat(dt: object) -> str:
    """converts a datetime to a string in eve format
    e.g. '2019-06-25T19:04:44'
    """
    from datetime import datetime

    dt2 = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    return dt2.isoformat()


def _generate_token(
    character_id: int,
    character_name: str,
    access_token: str = 'access_token',
    refresh_token: str = 'refresh_token',
    character_owner_hash: str = 'character_owner_hash',
    scopes=None,  # list or string from ccp
    timestamp_dt: object = None,
    expires_in: int = 1200,
    sso_version: int = 2
) -> dict:
    from datetime import datetime, timedelta

    if timestamp_dt is None:
        timestamp_dt = datetime.utcnow()
    if scopes is None:
        scopes = [
            'esi-mail.read_mail.v1',
            'esi-wallet.read_character_wallet.v1',
            'esi-universe.read_structures.v1'
        ]
    token = {
        'access_token': access_token,
        'expires_in': expires_in,
        'refresh_token': refresh_token,
        'timestamp': int(timestamp_dt.timestamp()),
        'character_id': character_id,
        'name': character_name,
        'ExpiresOn': _dt_eveformat(timestamp_dt + timedelta(seconds=expires_in)),
        'scp': scopes,
        'token_type': 'character',
        'owner': character_owner_hash,
        'IntellectualProperty': 'EVE',
        'sso_version': sso_version
    }
    return token


def _store_as_Token(token: dict, user: object) -> object:
    """Stores a generated token dict as Token object for given user

    returns Token object
    """
    from ..models import Scope, Token

    obj = Token.objects.create(
        access_token=token['access_token'],
        refresh_token=token['refresh_token'],
        user=user,
        character_id=token['character_id'],
        character_name=token['name'],
        token_type=token['token_type'],
        character_owner_hash=token['owner'],
        sso_version=token['sso_version']
    )

    if isinstance(token['scp'], str):
        token['scp'] = [token['scp']]

    for scope_name in token['scp']:
        scope, _ = Scope.objects.get_or_create(
            name=scope_name
        )
        obj.scopes.add(scope)

    return obj


class SocketAccessError(Exception):
    """Error raised when a test script accesses the network"""


class NoSocketsTestCase(TestCase):
    """Variation of Django's TestCase class that prevents any network use.

    Example:

        .. code-block:: python

            class TestMyStuff(NoSocketsTestCase):
                def test_should_do_what_i_need(self):
                    ...

    """
    @classmethod
    def setUpClass(cls):
        cls.socket_original = socket.socket
        socket.socket = cls.guard
        return super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        socket.socket = cls.socket_original
        return super().tearDownClass()

    @staticmethod
    def guard(*args, **kwargs):
        raise SocketAccessError("Attempted to access network")
