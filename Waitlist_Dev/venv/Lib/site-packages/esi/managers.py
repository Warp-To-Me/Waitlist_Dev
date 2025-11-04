import logging
from datetime import timedelta
from typing import Any, Union

import requests
from django.db import models
from django.utils import timezone
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from requests_oauthlib import OAuth2Session

from . import app_settings
from .errors import IncompleteResponseError, TokenError

logger = logging.getLogger(__name__)


def _process_scopes(scopes):
    if scopes is None:
        # support filtering by no scopes with None passed
        scopes = []
    if not isinstance(scopes, models.QuerySet) and len(scopes) == 1:
        # support a single space-delimited string inside a list because :users:
        scopes = scopes[0]
    # support space-delimited string scopes or lists
    if isinstance(scopes, str):
        scopes = set(scopes.split())
    return {str(s) for s in scopes}


class TokenQueryset(models.QuerySet):
    def get_expired(self) -> models.QuerySet:
        """Get all tokens which have expired.

        Returns:
            All expired tokens.
        """
        max_age = \
            timezone.now() - timedelta(seconds=app_settings.ESI_TOKEN_VALID_DURATION)
        return self.filter(created__lte=max_age)

    def bulk_refresh(self) -> models.QuerySet:
        """Refresh all refreshable tokens in the queryset and delete any expired token
        that fails to refresh or can not be refreshed.

        Excludes tokens for which the refresh was incomplete for other reasons.

        Returns:
            All refreshed tokens
        """
        session = OAuth2Session(app_settings.ESI_SSO_CLIENT_ID)
        auth = requests.auth.HTTPBasicAuth(
            app_settings.ESI_SSO_CLIENT_ID, app_settings.ESI_SSO_CLIENT_SECRET
        )
        incomplete = []
        for model in self.filter(refresh_token__isnull=False):
            try:
                model.refresh(session=session, auth=auth)
                logging.debug("Successfully refreshed %r", model)
            except TokenError:
                logger.info("Refresh failed for %r. Deleting.", model)
                model.delete()
            except IncompleteResponseError:
                incomplete.append(model.pk)
        self.filter(refresh_token__isnull=True).get_expired().delete()
        return self.exclude(pk__in=incomplete)

    def require_valid(self) -> models.QuerySet:
        """Ensure all tokens are still valid and attempt to refresh any which are expired

        Deletes those which fail to refresh or cannot be refreshed.

        Returns:
            All tokens which are still valid.
        """
        expired_pks = set(self.get_expired().values_list("pk", flat=True))
        fresh_pks = set(self.exclude(pk__in=expired_pks).values_list("pk", flat=True))
        refreshed = self.filter(pk__in=expired_pks).bulk_refresh()
        refreshed_pks = set(refreshed.values_list("pk", flat=True))
        qs = self.filter(pk__in=fresh_pks | refreshed_pks)
        return qs

    def require_scopes(self, scope_string: Union[str, list]) -> models.QuerySet:
        """Filter tokens which have at least a subset of given scopes.

        Args:
            scope_string: The required scopes.

        Returns:
            Tokens which have all requested scopes.
        """
        scopes = _process_scopes(scope_string)
        if not scopes:
            # asking for tokens with no scopes
            return self.filter(scopes__isnull=True)
        from .models import Scope
        scope_pks = Scope.objects.filter(name__in=scopes).values_list('pk', flat=True)
        if not len(scopes) == len(scope_pks):
            # there's a scope we don't recognize, so we can't have any tokens for it
            return self.none()
        tokens = self.all()
        for pk in scope_pks:
            tokens = tokens.filter(scopes__pk=pk)
        return tokens

    def require_scopes_exact(self, scope_string: Union[str, list]) -> models.QuerySet:
        """Filter tokens which exactly have the given scopes.

        Args:
            scope_string: The required scopes.

        Returns:
            Tokens which have all requested scopes.
        """
        num_scopes = len(_process_scopes(scope_string))
        scopes_qs = self\
            .annotate(models.Count('scopes'))\
            .require_scopes(scope_string)\
            .filter(scopes__count=num_scopes)\
            .values('pk', 'scopes__id')
        pks = [v['pk'] for v in scopes_qs]
        return self.filter(pk__in=pks)

    def equivalent_to(self, token) -> models.QuerySet:
        """Fetch all tokens which match the character and scopes of given reference token

        Args:
            token: :class:`esi.models.Token` reference token
        """
        return self\
            .filter(character_id=token.character_id)\
            .require_scopes_exact(token.scopes.all())\
            .filter(models.Q(user=token.user) | models.Q(user__isnull=True))\
            .exclude(pk=token.pk)


class TokenManager(models.Manager):
    def get_queryset(self):
        """
        Replace base queryset model with custom TokenQueryset
        :rtype: :class:`esi.managers.TokenQueryset`
        """
        return TokenQueryset(self.model, using=self._db)

    @staticmethod
    def _decode_jwt(jwt_token: dict, jwk_set: dict, issuer: Any):
        """
        Helper function to decide the JWT access token supplied by EVE SSO
        """
        logger.debug("Start Decode")
        token_data = jwt.decode(
            jwt_token,
            jwk_set,
            algorithms=jwk_set["alg"],
            audience=app_settings.ESI_TOKEN_JWT_AUDIENCE,
            issuer=issuer
        )
        token_detail = token_data.get("sub", None).split(":")
        token_data['character_id'] = int(token_detail[2])
        token_data['token_type'] = token_detail[0].lower()
        logger.debug(token_data)
        return token_data

    @staticmethod
    def validate_access_token(token: str):
        """
        Validate a JWT token retrieved from the EVE SSO.
        :param token: A JWT token originating from the EVE SSO v2
        :return: :class:`dict` The contents of the validated JWT token if
            there are no validation errors
        """

        res = requests.get(app_settings.ESI_TOKEN_JWK_SET_URL)
        res.raise_for_status()
        data = res.json()

        try:
            jwk_sets = data["keys"]
        except KeyError as e:
            logger.warning(
                "Something went wrong when retrieving the JWK set. "
                "The returned payload did not have the expected key %s.\n"
                "Payload returned from the SSO looks like: %s",
                e,
                data
            )
            return None

        jwk_set = [item for item in jwk_sets if item["alg"] == "RS256"].pop()
        try:
            return TokenManager._decode_jwt(
                token,
                jwk_set,
                ("login.eveonline.com", "https://login.eveonline.com")
            )
        except ExpiredSignatureError:
            logger.warning("The JWT token has expired")
            return None
        except JWTError as e:
            logger.warning("The JWT signature was invalid: %s", e)
            return None

    def create_from_code(self, code, user=None):
        """
        Perform OAuth code exchange to retrieve a token.
        :param code: OAuth grant code.
        :param user: User who will own token.
        :return: :class:`esi.models.Token`
        """

        # perform code exchange
        logger.debug("Creating new token from code %s", code[:-5])
        oauth = OAuth2Session(
            app_settings.ESI_SSO_CLIENT_ID,
            redirect_uri=app_settings.ESI_SSO_CALLBACK_URL
        )
        token = oauth.fetch_token(
            app_settings.ESI_TOKEN_URL,
            client_secret=app_settings.ESI_SSO_CLIENT_SECRET,
            code=code
        )

        token_data = TokenManager.validate_access_token(token.get('access_token', None))

        # translate returned data to a model
        model = self.create(
            character_id=token_data['character_id'],
            character_name=token_data['name'],
            character_owner_hash=token_data['owner'],
            access_token=token['access_token'],
            refresh_token=token['refresh_token'],
            token_type=token_data['token_type'],
            user=user,
        )

        # parse scopes
        if 'scp' in token_data:
            from esi.models import Scope

            # if a single scope is supplied its a string... recast to list
            if isinstance(token_data['scp'], str):
                token_data['scp'] = [token_data['scp']]

            for s in token_data['scp']:
                try:
                    scope = Scope.objects.get(name=s)
                    model.scopes.add(scope)
                except Scope.DoesNotExist:
                    # This scope isn't included in a data migration.
                    # Create a placeholder until it updates.
                    try:
                        help_text = s.split('.')[1].replace('_', ' ').capitalize()
                    except IndexError:
                        # Unusual scope name, missing periods.
                        help_text = s.replace('_', ' ').capitalize()
                    scope = Scope.objects.create(name=s, help_text=help_text)
                    model.scopes.add(scope)
            logger.debug("Added %d scopes to new token.", model.scopes.all().count())

        if not app_settings.ESI_ALWAYS_CREATE_TOKEN:
            # see if we already have a token for this character and scope combination
            # if so, we don't need a new one
            queryset = self.get_queryset().equivalent_to(model)
            if queryset.exists():
                logger.debug(
                    "Identified %d tokens equivalent to new token. "
                    "Updating access and refresh tokens.",
                    queryset.count()
                )
                queryset.update(
                    access_token=model.access_token,
                    refresh_token=model.refresh_token,
                    created=model.created,
                )
                if queryset.filter(user=model.user).exists():
                    logger.debug(
                        "Equivalent token with same user exists. Deleting new token."
                    )
                    model.delete()
                    model = queryset.filter(user=model.user)[0]  # pick one at random

        logger.debug("Successfully created %r for user %s", model, user)
        return model

    def create_from_request(self, request):
        """
        Generate a token from the OAuth callback request. Must contain 'code' in GET.
        :param request: OAuth callback request.
        :return: :class:`esi.models.Token`
        """
        logger.debug(
            "Creating new token for %s session %s",
            request.user,
            request.session.session_key[:5]
        )
        code = request.GET.get('code')
        # attach a user during creation for some functionality in a post_save created
        # receiver I'm working on elsewhere
        model = self.create_from_code(
            code, user=request.user if request.user.is_authenticated else None
        )
        return model
