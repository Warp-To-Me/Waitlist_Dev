import logging
import requests
from django.utils import timezone
from esi.models import Token
from esi.clients import EsiClientProvider
from bravado.exception import HTTPNotFound, HTTPForbidden, HTTPBadGateway, HTTPUnauthorized, HTTPInternalServerError, HTTPGatewayTimeout
from .models import EveCharacter, Fleet
from .exceptions import (
    EsiException, EsiTokenAuthFailure, EsiScopeMissing, 
    EsiForbidden, EsiNotFound
)

logger = logging.getLogger(__name__)

# --- ESI CLIENT PROVIDER ---

def get_esi_client() -> EsiClientProvider:
    """
    Returns an initialized ESI client.
    """
    return EsiClientProvider()

# --- TOKEN MANAGEMENT ---

def get_refreshed_token_for_character(character: EveCharacter, required_scopes: list = None) -> Token:
    """
    Fetches and, if necessary, refreshes the ESI token for a character.
    Raises custom EsiException errors on failure.

    :param character: The EveCharacter object.
    :param required_scopes: A list of scope strings to check for.
    :raises EsiTokenAuthFailure: If token is not found or is invalid/revoked.
    :raises EsiScopeMissing: If the token is valid but lacks required scopes.
    :raises EsiException: For any other unexpected ESI error.
    """
    try:
        # 1. Get the latest token from django-esi
        token = Token.objects.filter(
            user_id=character.user_id, 
            character_id=character.character_id
        ).order_by('-created').first()
        
        if not token:
            logger.warning(f"No ESI token found for character {character.character_id}")
            raise EsiTokenAuthFailure("No ESI token found for this character.")

        # 2. Check scopes if required
        if required_scopes:
            available_scopes = set(token.scopes.all().values_list('name', flat=True))
            missing_scopes = set(required_scopes) - available_scopes
            if missing_scopes:
                logger.warning(f"Token for {character.character_name} is missing scopes: {missing_scopes}")
                raise EsiScopeMissing(f"Missing required scopes: {', '.join(missing_scopes)}")

        # 3. Check expiry and refresh if needed
        if not character.token_expiry or character.token_expiry < timezone.now():
            logger.info(f"Refreshing ESI token for {character.character_name} ({character.character_id})")
            token.refresh()
            
            # Sync our local EveCharacter model
            character.access_token = token.access_token
            # .expires is an in-memory attribute added by .refresh()
            character.token_expiry = token.expires 
            
            # Also refresh public data on token refresh
            try:
                public_data = get_character_public_data(character.character_id)
                character.corporation_id = public_data.get('corporation_id')
                character.corporation_name = public_data.get('corporation_name')
                character.alliance_id = public_data.get('alliance_id')
                character.alliance_name = public_data.get('alliance_name')
            except EsiException as e:
                # Log the error but don't fail the token refresh
                logger.error(f"Could not refresh public data during token refresh for {character.character_name}: {e}")
            
            character.save()
            logger.info(f"Token refreshed successfully for {character.character_name}")
            
        return token

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            # 400 Bad Request on refresh means the refresh token is invalid/revoked
            logger.error(f"ESI token refresh failed for {character.character_name}. Token is invalid/revoked.")
            raise EsiTokenAuthFailure("Your ESI token is invalid or has been revoked. Please log out and back in.")
        else:
            logger.error(f"ESI HTTPError during token refresh for {character.character_name}: {e}")
            raise EsiException(f"ESI HTTP Error: {e.response.text}", e.response.status_code)
    except Token.DoesNotExist:
        logger.warning(f"Token.DoesNotExist raised for {character.character_name}")
        raise EsiTokenAuthFailure("Could not find a valid ESI token for this character.")
    except EsiException:
        # Re-raise our own exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected token error for {character.character_name}: {e}", exc_info=True)
        raise EsiException(f"An unexpected token error occurred: {e}")


# --- ESI CALL WRAPPER ---

def make_esi_call(esi_operation, character: EveCharacter = None, required_scopes: list = None, **kwargs):
    """
    A central wrapper for all ESI calls.
    - Gets a valid token for the character (if provided).
    - Checks for required scopes (if provided).
    - Makes the ESI call with provided kwargs.
    - Catches bravado exceptions and raises custom EsiExceptions.

    :param esi_operation: The ESI client operation (e.g., esi.client.Fleets.get_fleets_fleet_id_members)
    :param character: The EveCharacter making the call (if authenticated).
    :param required_scopes: A list of scope strings to check for.
    :param kwargs: Any arguments to pass to the ESI operation (e.g., fleet_id=123).
    """
    token = None
    if character:
        # This will raise EsiTokenAuthFailure or EsiScopeMissing on its own
        token = get_refreshed_token_for_character(character, required_scopes)
        kwargs['token'] = token.access_token

    try:
        # Make the ESI call
        logger.debug(f"Making ESI call: {esi_operation.operation.operation_id} with args {kwargs.keys()}")
        esi_result = esi_operation(**kwargs)
        
        # .results() blocks until the call is complete and returns the data
        # or raises an exception
        return esi_result.results()

    # --- Handle ESI Errors ---
    except HTTPUnauthorized as e:
        # This can happen if a token expires *just* before a call
        logger.warning(f"ESI 401 Unauthorized for {character.character_name} on {esi_operation.operation.operation_id}. Retrying once.")
        try:
            # Force a refresh
            character.token_expiry = timezone.now() - timezone.timedelta(minutes=1)
            character.save()
            token = get_refreshed_token_for_character(character, required_scopes)
            kwargs['token'] = token.access_token
            
            # Retry the call
            return esi_operation(**kwargs).results()
        except Exception as retry_e:
            logger.error(f"ESI retry failed for {character.character_name}: {retry_e}")
            raise EsiTokenAuthFailure(f"ESI Unauthorized: {e.response.text}", e.response.status_code)
            
    except HTTPForbidden as e:
        logger.warning(f"ESI 403 Forbidden for {character.character_name} on {esi_operation.operation.operation_id}")
        raise EsiForbidden(f"ESI Forbidden: {e.response.text}", e.response.status_code)
        
    except HTTPNotFound as e:
        logger.debug(f"ESI 404 Not Found on {esi_operation.operation.operation_id}")
        raise EsiNotFound(f"ESI Not Found: {e.response.text}", e.response.status_code)

    except (HTTPBadGateway, HTTPInternalServerError, HTTPGatewayTimeout) as e:
        logger.error(f"ESI 5xx Server Error on {esi_operation.operation.operation_id}: {e}")
        raise EsiException(f"ESI Server Error: {e.response.text}", e.response.status_code)

    except EsiException:
        # Re-raise exceptions from get_refreshed_token_for_character
        raise
        
    except Exception as e:
        # Catch any other unexpected error
        logger.error(f"Unexpected ESI error on {esi_operation.operation.operation_id}: {e}", exc_info=True)
        raise EsiException(f"An unexpected error occurred: {e}")


# --- PUBLIC DATA CONVENIENCE FUNCTIONS ---

def get_character_public_data(character_id: int) -> dict:
    """
    Fetches public character, corporation, and alliance data.
    This is an unauthenticated call.
    """
    esi = get_esi_client()
    try:
        public_data = make_esi_call(
            esi.client.Character.get_characters_character_id,
            character_id=character_id
        )
        
        corp_id = public_data.get('corporation_id')
        alliance_id = public_data.get('alliance_id')
        
        corp_name = None
        if corp_id:
            corp_data = make_esi_call(
                esi.client.Corporation.get_corporations_corporation_id,
                corporation_id=corp_id
            )
            corp_name = corp_data.get('name')
            
        alliance_name = None
        if alliance_id:
            try:
                alliance_data = make_esi_call(
                    esi.client.Alliance.get_alliances_alliance_id,
                    alliance_id=alliance_id
                )
                alliance_name = alliance_data.get('name')
            except EsiNotFound:
                logger.warning(f"Could not find alliance {alliance_id} for char {character_id} (dead alliance?)")
                alliance_name = "N/A" # Handle dead alliances

        return {
            "corporation_id": corp_id,
            "corporation_name": corp_name,
            "alliance_id": alliance_id,
            "alliance_name": alliance_name,
        }
    except EsiException as e:
        logger.error(f"Error fetching public data for {character_id}: {e}", exc_info=True)
        # Fail gracefully
        return {}