import datetime
import re
import logging
from typing import ClassVar

from bravado.client import SwaggerClient
from requests.auth import HTTPBasicAuth
from requests_oauthlib import OAuth2Session
from oauthlib.oauth2.rfc6749.errors import (
    InvalidClientError,
    InvalidClientIdError,
    InvalidGrantError,
    InvalidTokenError,
    MissingTokenError,
)

from django.core.exceptions import ImproperlyConfigured
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import app_settings
from .clients import esi_client_factory
from .managers import TokenManager
from .errors import (
    IncompleteResponseError,
    NotRefreshableTokenError,
    TokenExpiredError,
    TokenInvalidError,
    TokenError
)


logger = logging.getLogger(__name__)


class Scope(models.Model):
    """
    Represents an access scope granted by SSO.
    """
    name = models.CharField(
        max_length=100, unique=True, help_text="The official EVE name for the scope."
    )
    help_text = models.TextField(help_text="The official EVE description of the scope.")

    @property
    def friendly_name(self):
        return self._friendly_name(self.name)

    @classmethod
    def _friendly_name(cls, name):
        try:
            return re.sub('_', ' ', name.split('.')[1]).strip()
        except IndexError:
            return name

    def __str__(self) -> str:
        return self.name


class Token(models.Model):
    """EVE Swagger Interface Access Token

    Contains information about the authenticating character
    and scopes granted to this token.
    Contains the access token required for ESI authentication as well as refreshing.
    """

    TOKEN_TYPE_CHARACTER = "character"
    TOKEN_TYPE_CORPORATION = "corporation"
    TOKEN_TYPE_CHOICES = [
        (TOKEN_TYPE_CHARACTER, _('Character')),
        (TOKEN_TYPE_CORPORATION, _('Corporation')),
    ]

    created = models.DateTimeField(auto_now_add=True)
    access_token = models.TextField(
        help_text="The access token granted by SSO.",
        editable=False
    )
    refresh_token = models.TextField(
        null=True,  # refresh tokens returned from SSO can be null
        help_text="A re-usable token to generate new access tokens upon expiry.",
        editable=False
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        help_text="The user to whom this token belongs."
    )
    character_id = models.IntegerField(
        db_index=True,
        help_text="The ID of the EVE character who authenticated by SSO."
    )
    character_name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="The name of the EVE character who authenticated by SSO."
    )
    token_type = models.CharField(
        max_length=100,
        choices=TOKEN_TYPE_CHOICES,
        default=TOKEN_TYPE_CHARACTER,
        help_text="The applicable range of the token."
    )
    character_owner_hash = models.CharField(
        max_length=254,
        db_index=True,
        help_text=(
            "The unique string identifying this character and its owning EVE "
            "account. Changes if the owning account changes."
        )
    )
    scopes = models.ManyToManyField(
        Scope, blank=True, help_text="The access scopes granted by this token."
    )
    sso_version = models.IntegerField(
        help_text="EVE SSO Version.",
        default=2
    )

    objects: ClassVar[TokenManager] = TokenManager()

    def __str__(self) -> str:
        try:
            scopes = sorted(s.name for s in self.scopes.all())
        except ValueError:
            scopes = []
        return f'{self.character_name} - {", ".join(scopes)}'

    def __repr__(self) -> str:
        return "<{}(id={}): {}, {}>".format(
            self.__class__.__name__,
            self.pk,
            self.character_id,
            self.character_name,
        )

    @property
    def can_refresh(self) -> bool:
        """Determine if this token can be refreshed upon expiry."""
        return bool(self.refresh_token)

    @property
    def expires(self) -> datetime.datetime:
        """Determines when this token expires.

        Returns:
            Date & time when this token expires
        """
        return (
            self.created
            + datetime.timedelta(seconds=app_settings.ESI_TOKEN_VALID_DURATION)
        )

    @property
    def expired(self) -> bool:
        """Determines if this token has expired."""
        return self.expires < timezone.now()

    def valid_access_token(self) -> str:
        """Refresh and return access token to be used in an authed ESI call.

        Example:
            .. code-block:: python

                # fetch medals for a character
                medals = esi.client.Character.get_characters_character_id_medals(
                    # required parameter for endpoint
                    character_id = token.character_id,
                    # provide a valid access token, which will be refreshed if required
                    token = token.valid_access_token()
                ).results()

        Returns:
           Valid access token

        Raises:
            TokenExpiredError: When token can not be refreshed
        """
        if self.expired:
            if self.can_refresh:
                self.refresh()
            else:
                raise TokenExpiredError()
        return self.access_token

    def refresh(
        self, session: OAuth2Session = None, auth: HTTPBasicAuth = None
    ) -> None:
        """Refresh this token.

        Args:
            session: session for refreshing token with
            auth: ESI authentication
        """
        logger.debug("Attempting refresh of %r", self)
        if self.can_refresh:
            if not session:
                session = OAuth2Session(app_settings.ESI_SSO_CLIENT_ID)
            if not auth:
                auth = HTTPBasicAuth(
                    app_settings.ESI_SSO_CLIENT_ID, app_settings.ESI_SSO_CLIENT_SECRET
                )
            try:
                token = session.refresh_token(
                    app_settings.ESI_TOKEN_URL,
                    refresh_token=self.refresh_token,
                    auth=auth
                )
                logger.debug("Retrieved new token from SSO servers.")
                # logger.debug(token)
                token_data = TokenManager.validate_access_token(token['access_token'])

                # TODO verify token properly
                if token_data is not None:
                    if self.character_owner_hash != token_data['owner']:
                        logger.warning("Invalid Owner")
                        raise InvalidTokenError("Ownership Changed! Revoke me!")

                self.access_token = token['access_token']
                self.refresh_token = token['refresh_token']
                self.sso_version = 2  # we will never be ssov1 again
                self.created = timezone.now()
                self.save()
                logger.debug("Successfully refreshed %r", self)
            except (InvalidGrantError) as e:
                # this token is gone forever
                logger.error("Refresh impossible for %r: %r", self, e)
                raise TokenInvalidError()
            except (InvalidTokenError, InvalidClientIdError) as e:
                # these may be recoverable?
                logger.warning("Refresh failed for %r: %r", self, e)
                raise TokenInvalidError()
            except MissingTokenError as e:
                logger.info("Refresh failed for %r: %r", self, e)
                raise IncompleteResponseError()
            except InvalidClientError:
                logger.debug(
                    "ESI client ID and secret rejected by remote. Cannot refresh."
                )
                raise ImproperlyConfigured(
                    'Verify ESI_SSO_CLIENT_ID and ESI_SSO_CLIENT_SECRET settings.'
                )
        else:
            logger.debug("Not a refreshable token.")
            raise NotRefreshableTokenError()

    def refresh_or_delete(self) -> None:
        """Refresh this token or delete it if it can not be refreshed."""
        try:
            self.refresh()
        except TokenError:
            self.delete()
            logger.warning("%s: Refresh failed. Token deleted.", repr(self))
        else:
            logging.info("%s: Successfully refreshed", self)

    def get_esi_client(self, **kwargs) -> SwaggerClient:
        """Creates an authenticated ESI client with this token.

        Args:
            **kwargs: Extra spec versioning as per \
                :class:`esi.clients.esi_client_factory`

        Returns:
            New ESI client
        """
        return esi_client_factory(token=self, **kwargs)

    @classmethod
    def get_token_data(cls, access_token):
        return TokenManager.validate_access_token(access_token)

    # unused?
    def update_token_data(self, commit=True):
        logger.debug("Updating token data for %r", self)
        if self.expired:
            if self.can_refresh:
                self.refresh()
            else:
                raise TokenExpiredError()
        token_data = self.get_token_data(self.access_token)
        logger.debug(token_data)
        self.character_id = token_data['character_id']
        self.character_name = token_data['name']
        self.character_owner_hash = token_data['owner']
        self.token_type = token_data['token_type']
        logger.debug("Successfully updated token data.")
        if commit:
            self.save()

    @classmethod
    def get_token(cls, character_id: int, scopes: list) -> "Token":
        """Helper method to get a token for a specific character with specific scopes.

        Args:
            character_id: Character to filter on.
            scopes: array of ESI scope strings to search for.

        Returns:
            Matching token or `False` when token is not found
        """
        token = (
            Token.objects
            .filter(character_id=character_id)
            .require_scopes(scopes)
            .first()
        )
        if token:
            return token
        else:
            return False


class CallbackRedirect(models.Model):
    """
    Records the intended destination for the SSO callback.
    Used to internally redirect SSO callbacks.
    """
    session_key = models.CharField(
        max_length=254,
        unique=True,
        help_text="Session key identifying the session this redirect was created for."
    )
    url = models.TextField(
        default="/",
        help_text="The internal URL to redirect this callback towards."
    )
    state = models.CharField(
        max_length=128,
        help_text="OAuth2 state string representing this session."
    )
    created = models.DateTimeField(auto_now_add=True)
    token = models.ForeignKey(
        Token,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        help_text=(
            "Token generated by a completed code exchange "
            "from callback processing."
        )
    )

    def __str__(self) -> str:
        return f"{self.session_key}: {self.url}"

    def __repr__(self) -> str:
        return "<{}(pk={}): {} to {}>".format(
            self.__class__.__name__, self.pk,
            self.session_key, self.url
        )
