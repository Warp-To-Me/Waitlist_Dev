import logging
from django.utils import timezone
import requests
from esi.models import Token
from esi.clients import EsiClientProvider
from bravado.exception import HTTPNotFound
from .models import FleetWing, FleetSquad, EveCharacter, Fleet

logger = logging.getLogger(__name__)

def is_fleet_commander(user):
    """
    Checks if a user is in the 'Fleet Commander' group.
    """
    return user.groups.filter(name='Fleet Commander').exists()


def get_refreshed_token_for_character(user, character: EveCharacter):
    """
    Fetches and, if necessary, refreshes the ESI token for a character.
    Raises an exception on auth failure.
    (Based on the version in waitlist/views.py)
    """
    try:
        token = Token.objects.filter(
            user=user, 
            character_id=character.character_id
        ).order_by('-created').first()
        
        if not token:
            logger.warning(f"No ESI token found for character {character.character_id}")
            raise Token.DoesNotExist

        # Handle token_expiry being None (e.g., on first login)
        if not character.token_expiry or character.token_expiry < timezone.now():
            logger.info(f"Refreshing ESI token for {character.character_name} ({character.character_id})")
            token.refresh()
            character.access_token = token.access_token
            # .expires is an in-memory attribute added by .refresh()
            character.token_expiry = token.expires 
            character.save()
            logger.info(f"Token refreshed successfully for {character.character_name}")
            
        return token

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            # Refresh token is invalid.
            logger.error(f"ESI token refresh failed for {character.character_name}. Token is invalid/revoked.")
            raise Exception("Your ESI token is invalid or has been revoked. Please log out and back in.")
        else:
            logger.error(f"ESI HTTPError during token refresh for {character.character_name}: {e}")
            raise e # Re-raise other ESI errors
    except Token.DoesNotExist:
        logger.warning(f"Token.DoesNotExist raised for {character.character_name}")
        raise Exception("Could not find a valid ESI token for this character.")
    except Exception as e:
        # Catch other errors, like TypeError if token_expiry is None
        logger.error(f"Unexpected token error for {character.character_name}: {e}", exc_info=True)
        raise Exception(f"An unexpected token error occurred: {e}")


def _update_fleet_structure(esi: EsiClientProvider, fc_character: EveCharacter, token: Token, fleet_id: int, fleet_obj: Fleet):
    """
    Pulls ESI fleet structure and saves it to the DB.
    *** This preserves existing category mappings. ***
    """
    logger.debug(f"Updating fleet structure for fleet {fleet_id} (Fleet Obj: {fleet_obj.id})")
    # 1. Get wings from ESI
    try:
        wings = esi.client.Fleets.get_fleets_fleet_id_wings(
            fleet_id=fleet_id,
            token=token.access_token
        ).results()
        logger.debug(f"Found {len(wings)} wings in ESI")
    except HTTPNotFound:
        logger.warning(f"HTTPNotFound while fetching fleet wings for fleet {fleet_id}. Fleet may be closed.")
        # Re-raise so the calling view can handle it
        raise
    
    # 2. Get all *existing* category mappings from the DB before clearing
    existing_mappings = {
        s.squad_id: s.assigned_category
        for s in FleetSquad.objects.filter(wing__fleet=fleet_obj)
        if s.assigned_category is not None
    }
    logger.debug(f"Preserved {len(existing_mappings)} existing squad mappings")

    # 3. Clear old structure
    FleetWing.objects.filter(fleet=fleet_obj).delete() # This cascades and deletes squads
    
    # 4. Create new wings
    for wing in wings:
        new_wing = FleetWing.objects.create(
            fleet=fleet_obj,
            wing_id=wing['id'],
            name=wing['name']
        )
        
        # 5. Create new squads
        for squad in wing['squads']:
            # Restore category if this squad_id existed before
            restored_category = existing_mappings.get(squad['id'])
            
            FleetSquad.objects.create(
                wing=new_wing,
                squad_id=squad['id'],
                name=squad['name'], # Use the name from ESI
                assigned_category=restored_category # Restore the mapping
            )
    logger.info(f"Fleet structure update complete for fleet {fleet_id}")