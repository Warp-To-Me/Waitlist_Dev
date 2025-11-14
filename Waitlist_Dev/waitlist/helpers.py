import logging
from django.utils import timezone
# --- MODIFICATION: Removed requests, Token, ESI client ---
from .models import FleetWing, FleetSquad, EveCharacter, Fleet
# --- NEW: Import our new ESI service and exceptions ---
from . import esi
from .exceptions import EsiNotFound
# --- END NEW ---

logger = logging.getLogger(__name__)

def is_fleet_commander(user):
    """
    Checks if a user is in the 'Fleet Commander' group.
    """
    return user.groups.filter(name='Fleet Commander').exists()


# --- MODIFICATION: Removed get_refreshed_token_for_character function ---
# This logic is now centralized in waitlist/esi.py


def _update_fleet_structure(fleet_obj: Fleet):
    """
    Pulls ESI fleet structure and saves it to the DB.
    *** This preserves existing category mappings. ***
    --- MODIFIED: Now uses the central ESI service ---
    """
    
    # --- NEW: Get client and character from fleet object ---
    if not fleet_obj.fleet_commander or not fleet_obj.esi_fleet_id:
        logger.error(f"_update_fleet_structure called on unlinked fleet {fleet_obj.id}")
        return

    esi_client = esi.get_esi_client()
    fc_character = fleet_obj.fleet_commander
    fleet_id = fleet_obj.esi_fleet_id
    # --- END NEW ---
    
    logger.debug(f"Updating fleet structure for fleet {fleet_id} (Fleet Obj: {fleet_obj.id})")
    
    # 1. Get wings from ESI
    try:
        # --- MODIFICATION: Use make_esi_call wrapper ---
        wings = esi.make_esi_call(
            esi_client.client.Fleets.get_fleets_fleet_id_wings,
            character=fc_character,
            required_scopes=['esi-fleets.read_fleet.v1'],
            fleet_id=fleet_id
        )
        # --- END MODIFICATION ---
        logger.debug(f"Found {len(wings)} wings in ESI")
    except EsiNotFound: # MODIFIED exception
        logger.warning(f"EsiNotFound while fetching fleet wings for fleet {fleet_id}. Fleet may be closed.")
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