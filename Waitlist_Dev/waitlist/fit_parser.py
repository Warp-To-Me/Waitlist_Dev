# --- This file is a stub for future, more complex fit validation ---
# We are no longer using eveparse here.

# --- NEW: All parsing logic is now centralized here ---
import re
import json
from collections import Counter
import requests

from esi.clients import EsiClientProvider
from pilot.models import EveType, EveGroup
from .models import ShipFit
# from .models import FitCheckRule # This model doesn't exist yet

# --- HELPER FUNCTIONS (Copied from views.py) ---

def get_or_cache_eve_group(group_id):
    """
    Tries to get an EveGroup from the local DB.
    If not found, fetches from ESI and caches it.
    
    --- MODIFIED to use get_or_create to prevent race conditions ---
    """
    try:
        # get_or_create is atomic and prevents the race condition
        group, created = EveGroup.objects.get_or_create(
            group_id=group_id,
            defaults={'name': '...Fetching from ESI...'} # Temporary name
        )
        
        if created:
            # If we just created it, go update the name from ESI
            esi = EsiClientProvider()
            group_data = esi.client.Universe.get_universe_groups_group_id(
                group_id=group_id
            ).results()
            group.name = group_data['name']
            group.save()
            
        return group
    except Exception as e:
        # If ESI fails or DB fails, return None
        print(f"Error in get_or_cache_eve_group({group_id}): {e}")
        return None


def get_or_cache_eve_type(item_name):
    """
    Tries to get an EveType (ship, module, ammo) from the local DB by name.
    If not found, searches ESI, fetches details, and caches it.
    
    --- MODIFIED to use get_or_create to prevent race conditions ---
    """
    try:
        # First, try to get by name. This is fast and hits the cache.
        return EveType.objects.get(name__iexact=item_name)
    except EveType.DoesNotExist:
        try:
            # Not found by name. Go to ESI to get the ID.
            esi = EsiClientProvider()
            id_results = esi.client.Universe.post_universe_ids(
                names=[item_name] # Send a list with just our item name
            ).results()
            
            # 2. Check the results
            type_id = None
            if id_results.get('inventory_types'):
                type_id = id_results['inventory_types'][0]['id']
            elif id_results.get('categories'):
                type_id = id_results['categories'][0]['id']
            elif id_results.get('groups'):
                type_id = id_results['groups'][0]['id']
                
            if not type_id:
                return None # ESI couldn't find it
            
            # --- 3. NEW: Use get_or_create with the ID ---
            # This prevents a race condition if two items are processed
            # before the first one is saved.
            type_obj, created = EveType.objects.get_or_create(
                type_id=type_id,
                # We must provide defaults for all required fields
                defaults={
                    'name': '...Fetching from ESI...',
                    # We need a *valid* group, so we create a placeholder if we must
                    'group': get_or_cache_eve_group(0) or EveGroup.objects.get_or_create(group_id=0, defaults={'name': 'Unknown'})[0]
                }
            )

            if created:
                # If we just created it, fill in the correct details
                type_data = esi.client.Universe.get_universe_types_type_id(
                    type_id=type_id
                ).results()
                
                # Get the *actual* group
                group = get_or_cache_eve_group(type_data['group_id'])
                if not group:
                    # If group fetch fails, delete the placeholder type and fail
                    type_obj.delete()
                    return None
                    
                # 5. Get slot (if any)
                slot = None
                if 'dogma_attributes' in type_data:
                    for attr in type_data['dogma_attributes']:
                        if attr['attribute_id'] == 300: 
                            slot = int(attr['value'])
                            break
                
                # 6. Construct the icon URL
                icon_url = f"https://images.evetech.net/types/{type_id}/icon?size=32"

                # 7. Update the placeholder with the real data
                type_obj.name = type_data['name'] # Use canonical name
                type_obj.group = group
                type_obj.slot = slot
                type_obj.icon_url = icon_url
                type_obj.save()
            
            return type_obj
            
        except Exception as e:
            # ESI call or DB save failed
            print(f"Error in get_or_cache_eve_type({item_name}): {e}")
            return None
# --- END MODIFIED FUNCTIONS ---


# --- NEW PARSING FUNCTION FOR ADMIN ---

def parse_eft_to_json_summary(raw_fit_original: str):
    """
    Parses a raw EFT fit string and returns the ship_type object
    and a {type_id: quantity} summary dictionary.
    Used by the DoctrineFit admin form.
    """
    # 1. Minimal sanitization
    raw_fit_no_nbsp = raw_fit_original.replace(u'\xa0', u' ')
    lines = [line.strip() for line in raw_fit_no_nbsp.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Fit is empty or contains only whitespace.")

    # 2. Manually parse the header (first line)
    header_match = re.match(r'^\[(.*?),\s*(.*?)\]$', lines[0])
    if not header_match:
        raise ValueError("Could not find valid header. Fit must start with [Ship, Fit Name].")
        
    ship_name = header_match.group(1).strip()
    if not ship_name:
        raise ValueError("Ship name in header is empty.")

    # 3. Get the Type ID for the ship (this caches it)
    ship_type = get_or_cache_eve_type(ship_name)
    
    if not ship_type:
        raise ValueError(f"Ship hull '{ship_name}' could not be found in ESI. Check spelling.")
    
    # 4. Parse all items in the fit
    fit_summary_counter = Counter() # For auto-approval
    
    # Add the hull
    fit_summary_counter[ship_type.type_id] += 1

    # Regex to find item names and quantities
    item_regex = re.compile(r'^(.*?)(?:, .*)?(?: x(\d+))?$')

    # Loop through the rest of the lines
    for line in lines[1:]:
        if line.startswith('[') and line.endswith(']'):
            continue # Skip empty slots

        match = item_regex.match(line)
        if not match:
            continue
            
        item_name = match.group(1).strip()
        # --- THIS IS THE FIX ---
        # The quantity is in group 2, not 3
        quantity = int(match.group(2)) if match.group(2) else 1
        # --- END FIX ---
        
        if not item_name:
            continue

        item_type = get_or_cache_eve_type(item_name)
        
        if item_type:
            fit_summary_counter[item_type.type_id] += quantity
        else:
            # Could not find this item
            raise ValueError(f"Unknown item in fit: '{item_name}'. Check spelling or SDE cache.")
            
    # Return the ship object and the summary dict
    return ship_type, dict(fit_summary_counter)


# --- This is the original function, left as a placeholder ---
def parse_and_validate_fit(ship_fit: ShipFit):
    """
    Parses a ship fit and validates it against doctrine rules.
    
    This function is NOT called by the api_submit_fit view,
    which only does basic header parsing.
    
    This function could be called by an FC action (e.g., "Auto-Approve")
    or by a background task.
    """
    
    raw_text = ship_fit.raw_fit
    waitlist = ship_fit.waitlist
    character = ship_fit.character
    
    # For now, this is just a placeholder.
    # In the future, you could add logic here to:
    # 1. Parse all modules from raw_text (using regex or simple line splitting)
    # 2. Compare against FitCheckRule models associated with the waitlist
    # 3. Check character skills via ESI
    
    print(f"Placeholder: Validating fit {ship_fit.id} for {character.character_name}...")
    
    # Example placeholder logic
    if "Shield Booster" not in raw_text:
        ship_fit.fit_issues = "Missing Shield Booster"
        ship_fit.save()
        return False, "Missing Shield Booster"

    ship_fit.fit_issues = None
    ship_fit.save()
    return True, "Fit passes basic checks."