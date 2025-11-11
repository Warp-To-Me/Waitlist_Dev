from django.shortcuts import render, get_object_or_404, redirect, resolve_url
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import logout
from django.utils import timezone
from datetime import timedelta, datetime # --- Import datetime ---
import json
import requests # For handling HTTP errors during refresh
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from waitlist.models import EveCharacter
from .models import PilotSnapshot, EveGroup, EveType, EveCategory

from esi.clients import EsiClientProvider
from esi.models import Token
from bravado.exception import HTTPNotFound
from django.db import transaction

import logging
logger = logging.getLogger(__name__)


def is_fleet_commander(user):
    """
    Checks if a user is in the 'Fleet Commander' group.
    """
    return user.groups.filter(name='Fleet Commander').exists()


# --- HELPER FUNCTION: GET AND REFRESH TOKEN ---
def get_refreshed_token_for_character(user, character):
    """
    Fetches and, if necessary, refreshes the ESI token for a character.
    Handles auth failure by logging the user out.
    Returns the valid Token object or None if a redirect is needed.
    """
    try:
        token = Token.objects.filter(
            user=user, 
            character_id=character.character_id
        ).order_by('-created').first()
        
        if not token:
            logger.warning(f"No ESI token found for character {character.character_id}")
            raise Token.DoesNotExist

        if not character.token_expiry or character.token_expiry < timezone.now():
            logger.info(f"Refreshing ESI token for {character.character_name} ({character.character_id})")
            token.refresh()
            character.access_token = token.access_token
            character.token_expiry = token.expires # .expires is added in-memory by .refresh()
            
            # Refresh public data on token refresh
            esi = EsiClientProvider()
            try:
                logger.debug(f"Refreshing public data for {character.character_id}")
                public_data = esi.client.Character.get_characters_character_id(
                    character_id=character.character_id
                ).results()
                
                corp_id = public_data.get('corporation_id')
                alliance_id = public_data.get('alliance_id')
                
                corp_name = None
                if corp_id:
                    corp_data = esi.client.Corporation.get_corporations_corporation_id(
                        corporation_id=corp_id
                    ).results()
                    corp_name = corp_data.get('name')
                    
                alliance_name = None
                if alliance_id:
                    try:
                        alliance_data = esi.client.Alliance.get_alliances_alliance_id(
                            alliance_id=alliance_id
                        ).results()
                        alliance_name = alliance_data.get('name')
                    except HTTPNotFound:
                        logger.warning(f"Could not find alliance {alliance_id} for char {character.character_id} (dead alliance?)")
                        alliance_name = "N/A" # Handle dead alliances
                
                # Update character model
                character.corporation_id = corp_id
                character.corporation_name = corp_name
                character.alliance_id = alliance_id
                character.alliance_name = alliance_name
                logger.debug(f"Public data refreshed for {character.character_id}")
                
            except Exception as e:
                logger.error(f"Error refreshing public data for {character.character_id}: {e}", exc_info=True)
            
            character.save()
            logger.info(f"Token refreshed successfully for {character.character_name}")
            
        return token

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            # Refresh token is invalid. Delete token and character.
            logger.error(f"ESI token refresh failed for {character.character_name}. Token is invalid/revoked. Deleting character.")
            if 'token' in locals() and token:
                token.delete()
            character.delete()
            return None # Will cause a redirect
        else:
            logger.error(f"ESI HTTPError during token refresh for {character.character_name}: {e}")
            raise e # Re-raise other ESI errors
    except Token.DoesNotExist:
        logger.warning(f"Token.DoesNotExist raised for {character.character_name}")
        return None # Will cause a redirect
    except Exception as e:
        logger.error(f"Error in get_refreshed_token_for_character for {character.character_name}: {e}", exc_info=True)
        return None # Fail safely
# --- END HELPER FUNCTION ---


@login_required
def pilot_detail(request, character_id):
    """
    Displays the skills and implants for a specific character.
    This view is now FAST and only loads data from the database.
    It passes a flag to the template if a refresh is needed.
    """
    
    esi = EsiClientProvider()
    logger.debug(f"User {request.user.username} viewing pilot_detail for char {character_id}")
    character = get_object_or_404(EveCharacter, character_id=character_id, user=request.user)
    
    # 1. Get and refresh token (this is fast)
    token = get_refreshed_token_for_character(request.user, character)
    if not token:
        # Token was invalid, helper logged user out
        logger.warning(f"Token refresh failed for {character.character_name}, logging user {request.user.username} out.")
        logout(request)
        return redirect('esi_auth:login')

    # 2. Check scopes (fast)
    required_scopes = ['esi-skills.read_skills.v1', 'esi-clones.read_implants.v1']
    available_scopes = set(s.name for s in token.scopes.all())
    has_all_scopes = all(scope in available_scopes for scope in required_scopes)
    if not has_all_scopes:
        missing = [s for s in required_scopes if s not in available_scopes]
        logger.warning(f"User {request.user.username} missing scopes for {character.character_name}: {missing}. Redirecting to login.")
        return redirect(f"{resolve_url('esi_auth:login')}?scopes=regular")

    # 3. Get snapshot and check if it's stale
    snapshot, created = PilotSnapshot.objects.get_or_create(character=character)
    
    needs_update = False
    if created or snapshot.last_updated < (timezone.now() - timedelta(hours=1)):
        logger.debug(f"Snapshot for {character.character_name} is stale or was just created.")
        needs_update = True
    if not snapshot.skills_json or not snapshot.implants_json:
        logger.debug(f"Snapshot for {character.character_name} is missing skill/implant data.")
        needs_update = True
        
    # This view no longer runs the ESI update, it just sets the flag.
            
    # SDE & GROUPING LOGIC (This is fast, it reads from our DB)
    logger.debug(f"Loading skills from snapshot for {character.character_name}")
    grouped_skills = {}
    skills_list = snapshot.get_skills()
    if skills_list:
        all_skill_ids = [s['skill_id'] for s in skills_list]
        cached_types = {t.type_id: t for t in EveType.objects.filter(type_id__in=all_skill_ids).select_related('group')}
        
        # We ONLY show skills we have cached. The refresh API
        # will handle fetching any missing ones.
        for skill in skills_list:
            skill_id = skill['skill_id']
            if skill_id in cached_types:
                eve_type = cached_types[skill_id]
                group_name = eve_type.group.name
                
                if group_name not in grouped_skills:
                    grouped_skills[group_name] = []
                    
                grouped_skills[group_name].append({
                    'name': eve_type.name,
                    'level': skill['active_skill_level']
                })
    sorted_grouped_skills = dict(sorted(grouped_skills.items()))
    logger.debug(f"Loaded {len(skills_list)} skills into {len(sorted_grouped_skills)} groups")

    # IMPLANT LOGIC (This is fast, it reads from our DB)
    logger.debug(f"Loading implants from snapshot for {character.character_name}")
    all_implant_ids = snapshot.get_implant_ids()
    enriched_implants = []
    if all_implant_ids:
        cached_implant_types = {t.type_id: t for t in EveType.objects.filter(type_id__in=all_implant_ids).select_related('group')}
        
        for implant_id in all_implant_ids:
            if implant_id in cached_implant_types:
                eve_type = cached_implant_types[implant_id]
                enriched_implants.append({
                    'type_id': implant_id,
                    'name': eve_type.name,
                    'group_name': eve_type.group.name,
                    'slot': eve_type.slot if eve_type.slot else 0,
                    'icon_url': f"https://images.evetech.net/types/{implant_id}/icon?size=64"
                })
    
    sorted_implants = sorted(enriched_implants, key=lambda i: i.get('slot', 0))
    
    implants_other = []
    implants_col1 = [] # Slots 1-5
    implants_col2 = [] # Slots 6-10
    for implant in sorted_implants:
        slot = implant.get('slot', 0)
        if 0 < slot <= 5:
            implants_col1.append(implant)
        elif 5 < slot <= 10:
            implants_col2.append(implant)
        else:
            implants_other.append(implant)
    logger.debug(f"Loaded {len(enriched_implants)} implants")

    # Context logic for Main/Alts
    all_user_chars = request.user.eve_characters.all().order_by('character_name')
    main_char = all_user_chars.filter(is_main=True).first()
    if not main_char:
        main_char = all_user_chars.first()

    context = {
        'character': character,
        'implants_other': implants_other,
        'implants_col1': implants_col1,
        'implants_col2': implants_col2,
        'total_sp': snapshot.get_total_sp(),
        'snapshot_time': snapshot.last_updated,
        'portrait_url': f"https://images.evetech.net/characters/{character.character_id}/portrait?size=256",
        'grouped_skills': sorted_grouped_skills,
        'needs_refresh': needs_update, # Pass the flag!
        
        'is_fc': is_fleet_commander(request.user), # For base template
        'user_characters': all_user_chars, # For X-Up modal
        'all_chars_for_header': all_user_chars, # For header dropdown
        'main_char_for_header': main_char, # For header dropdown
    }
    
    return render(request, 'pilot_detail.html', context)


# --- NEW HELPER FUNCTION FOR SDE CACHING ---
def _cache_missing_eve_types(type_ids_to_check: list):
    """
    Checks a list of type IDs against the local SDE (EveType table)
    and fetches any missing ones from ESI.
    """
    if not type_ids_to_check:
        return

    logger.debug(f"Checking/caching {len(type_ids_to_check)} EveType IDs...")
    
    # Use set for efficient lookup
    type_ids_set = set(type_ids_to_check)
    
    # Find which types are already in our database
    cached_type_ids = set(EveType.objects.filter(
        type_id__in=type_ids_set
    ).values_list('type_id', flat=True))
    
    # Determine which IDs are missing
    missing_ids = list(type_ids_set - cached_type_ids)
    
    if not missing_ids:
        logger.debug("All EveTypes are already cached.")
        return

    logger.info(f"Found {len(missing_ids)} missing EveTypes to cache from ESI.")
    
    esi = EsiClientProvider()
    
    # Pre-fetch all groups from our DB to avoid multiple queries in the loop
    cached_groups = {g.group_id: g for g in EveGroup.objects.all()}
    
    for type_id in missing_ids:
        try:
            # 1. Fetch type data from ESI
            type_data = esi.client.Universe.get_universe_types_type_id(type_id=type_id).results()
            
            # 2. Find or create its group
            group_id = type_data['group_id']
            group = cached_groups.get(group_id)
            
            if not group:
                logger.debug(f"Caching new group {group_id} for type {type_id}")
                group_data = esi.client.Universe.get_universe_groups_group_id(group_id=group_id).results()
                category_id = group_data.get('category_id')
                
                # Try to get category from DB
                category = None
                if category_id:
                    try:
                        category = EveCategory.objects.get(category_id=category_id)
                    except EveCategory.DoesNotExist:
                        logger.warning(f"Could not find Category {category_id} for Group {group_id} while caching type {type_id}. This is fine if SDE is not fully imported.")
                        pass # Category might not exist if SDE import hasn't run
                
                group = EveGroup.objects.create(
                    group_id=group_id, 
                    name=group_data['name'],
                    category=category, # Link to category if found
                    published=group_data.get('published', True)
                )
                cached_groups[group.group_id] = group # Add to our in-memory cache
                logger.debug(f"Cached new group: {group.name}")

            # 3. Get implant slot (Dogma Attr 300) if it exists
            slot = None
            if 'dogma_attributes' in type_data:
                for attr in type_data['dogma_attributes']:
                    if attr['attribute_id'] == 300: # 300 = implantSlot
                        slot = int(attr['value'])
                        break
            
            # 4. Create the new EveType in our database
            EveType.objects.create(
                type_id=type_id, 
                name=type_data['name'], 
                group=group, 
                slot=slot, # Will be None if not an implant
                published=type_data.get('published', True),
                description=type_data.get('description'),
                mass=type_data.get('mass'),
                volume=type_data.get('volume'),
                capacity=type_data.get('capacity'),
                icon_id=type_data.get('icon_id'),
            )
            logger.debug(f"Cached new EveType: {type_data['name']} (ID: {type_id})")

        except Exception as e:
            logger.error(f"Failed to cache SDE for type_id {type_id}: {e}", exc_info=True)
            continue # Skip this one type and continue the loop

# --- END NEW HELPER FUNCTION ---


@login_required
def api_refresh_pilot(request, character_id):
    """
    This view runs in the background to fetch and cache all
    ESI data (snapshot and SDE) for a character.
    
    MODIFIED: Now accepts a '?section=' parameter to refresh
    only 'skills', 'implants', 'public', or 'all'.
    """
    
    # --- MODIFICATION: Check for section parameter ---
    # Default to 'all' if no section is specified (for the auto-refresh)
    section = request.GET.get('section', 'all')
    
    if request.method != 'POST': # Only allow POST requests
        logger.warning(f"api_refresh_pilot called with GET by {request.user.username}")
        return HttpResponseBadRequest("Invalid request method")

    logger.info(f"User {request.user.username} triggering ESI refresh for char {character_id} (section: {section})")
    esi = EsiClientProvider()
    character = get_object_or_404(EveCharacter, character_id=character_id, user=request.user)
    
    # 1. Get and refresh token
    token = get_refreshed_token_for_character(request.user, character)
    if not token:
        # User's token is invalid
        logger.error(f"api_refresh_pilot: Token refresh failed for {character_id}, logging user out")
        logout(request)
        return JsonResponse({"status": "error", "message": "Auth failed"}, status=401)
        
    try:
        # --- MODIFICATION: Granular refresh logic ---
        
        snapshot, created = PilotSnapshot.objects.get_or_create(character=character)
        all_type_ids_to_cache = set()

        # 2a. Fetch Skills
        if section == 'all' or section == 'skills':
            logger.debug(f"Fetching /skills/ for {character_id}")
            skills_response = esi.client.Skills.get_characters_character_id_skills(
                character_id=character_id,
                token=token.access_token
            ).results()
            if 'skills' not in skills_response or 'total_sp' not in skills_response:
                logger.error(f"Invalid skills response for {character_id}: {skills_response}")
                raise Exception(f"Invalid skills response: {skills_response}")
            
            snapshot.skills_json = json.dumps(skills_response)
            all_type_ids_to_cache.update(s['skill_id'] for s in skills_response.get('skills', []))
            logger.info(f"Skills snapshot updated for {character_id}")

        # 2b. Fetch Implants
        if section == 'all' or section == 'implants':
            logger.debug(f"Fetching /implants/ for {character_id}")
            implants_response = esi.client.Clones.get_characters_character_id_implants(
                character_id=character_id,
                token=token.access_token
            ).results()
            if not isinstance(implants_response, list):
                logger.error(f"Invalid implants response for {character_id}: {implants_response}")
                raise Exception(f"Invalid implants response: {implants_response}")

            snapshot.implants_json = json.dumps(implants_response)
            all_type_ids_to_cache.update(implants_response)
            logger.info(f"Implants snapshot updated for {character_id}")

        # 2c. Fetch Public Data (Corp/Alliance)
        if section == 'all' or section == 'public':
            logger.debug(f"Fetching public data for {character_id}")
            public_data = esi.client.Character.get_characters_character_id(
                character_id=character_id
            ).results()
            
            corp_id = public_data.get('corporation_id')
            alliance_id = public_data.get('alliance_id')
            
            corp_name = None
            if corp_id:
                corp_data = esi.client.Corporation.get_corporations_corporation_id(
                    corporation_id=corp_id
                ).results()
                corp_name = corp_data.get('name')
                
            alliance_name = None
            if alliance_id:
                try:
                    alliance_data = esi.client.Alliance.get_alliances_alliance_id(
                        alliance_id=alliance_id
                    ).results()
                    alliance_name = alliance_data.get('name')
                except HTTPNotFound:
                    logger.warning(f"Could not find alliance {alliance_id} for char {character.character_id} (dead alliance?)")
                    alliance_name = "N/A" # Handle dead alliances

            # Save corp/alliance data
            character.corporation_id = corp_id
            character.corporation_name = corp_name
            character.alliance_id = alliance_id
            character.alliance_name = alliance_name
            character.save()
            logger.info(f"Corp/Alliance data for {character_id} saved to DB")

        # 3. Save the snapshot with any new JSON
        snapshot.save() # This also updates 'last_updated'
        
        # 4. Perform SDE Caching for any new types we found
        if all_type_ids_to_cache:
            _cache_missing_eve_types(list(all_type_ids_to_cache))
        # --- END MODIFICATION ---

        # 5. All done, send success
        logger.info(f"ESI refresh complete for {character_id} (section: {section})")
        return JsonResponse({"status": "success", "section": section})

    except Exception as e:
        # Something went wrong during the ESI calls
        logger.error(f"Unexpected error in api_refresh_pilot for {character_id}: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def api_get_implants(request):
    """
    Fetches and returns a character's implants as HTML
    for the X-Up modal.
    """
    character_id = request.GET.get('character_id')
    logger.debug(f"User {request.user.username} getting implants for X-Up modal (char {character_id})")
    if not character_id:
        logger.warning(f"api_get_implants: Missing character_id")
        return HttpResponseBadRequest("Missing character_id")

    try:
        character = EveCharacter.objects.get(character_id=character_id, user=request.user)
    except EveCharacter.DoesNotExist:
        logger.warning(f"api_get_implants: User {request.user.username} tried to get implants for char {character_id} they don't own")
        return JsonResponse({"status": "error", "message": "Character not found or not yours."}, status=403)

    esi = EsiClientProvider()
    token = get_refreshed_token_for_character(request.user, character)
    if not token:
        logout(request)
        logger.error(f"api_get_implants: Token refresh failed for {character_id}, logging user out")
        return JsonResponse({"status": "error", "message": "Auth failed"}, status=401)
    
    # Check for correct scope
    if 'esi-clones.read_implants.v1' not in [s.name for s in token.scopes.all()]:
        logger.warning(f"api_get_implants: User {request.user.username} missing 'esi-clones.read_implants.v1' for {character_id}")
        return JsonResponse({"status": "error", "message": "Missing 'esi-clones.read_implants.v1' scope."}, status=403)

    try:
        # Make ESI call and get headers
        logger.debug(f"Fetching /implants/ for {character_id} (X-Up modal)")
        implants_op = esi.client.Clones.get_characters_character_id_implants(
            character_id=character_id,
            token=token.access_token
        )
        implants_response = implants_op.results()
        
        # Get Expiry header
        # --- THIS IS THE FIX ---
        # The .header attribute is on the *result* of the future,
        # which is accessed via `.future.result().header` after `.results()` is called.
        expires_str = implants_op.future.result().header.get('Expires', [None])[0]
        # --- END THE FIX ---
        
        expires_dt = None
        expires_iso = None
        if expires_str:
            try:
                # Parse the HTTP date string
                expires_dt = datetime.strptime(expires_str, '%a, %d %b %Y %H:%M:%S %Z').replace(tzinfo=timezone.utc)
                expires_iso = expires_dt.isoformat()
            except ValueError:
                expires_dt = timezone.now() + timedelta(minutes=2) # Fallback
                expires_iso = expires_dt.isoformat()
        else:
            expires_dt = timezone.now() + timedelta(minutes=2) # Fallback
            expires_iso = expires_dt.isoformat()
        logger.debug(f"Implant cache for {character_id} expires: {expires_iso}")

        if not isinstance(implants_response, list):
            logger.error(f"Invalid implants response for {character_id} (X-Up modal): {implants_response}")
            raise Exception("Invalid implants response")

        # --- REFACTORED SDE & GROUPING LOGIC ---
        all_implant_ids = implants_response # Response is just a list of IDs
        enriched_implants = []
        
        try:
            if all_implant_ids:
                # 1. Call the helper to cache any missing implant types
                _cache_missing_eve_types(all_implant_ids)
                
                # 2. Now, all types are guaranteed to be in our local DB.
                #    Fetch them all in one query.
                cached_types = {t.type_id: t for t in EveType.objects.filter(
                    type_id__in=all_implant_ids
                ).select_related('group')}

                # 3. Enrich the implant list
                for implant_id in all_implant_ids:
                    if implant_id in cached_types:
                        eve_type = cached_types[implant_id]
                        enriched_implants.append({
                            'name': eve_type.name,
                            'slot': eve_type.slot if eve_type.slot else 0,
                            'icon_url': f"https://images.evetech.net/types/{implant_id}/icon?size=32"
                        })
                    else:
                        # This should no longer happen, but good to log if it does
                        logger.warning(f"EveType {implant_id} was not found in DB after caching attempt.")

        except Exception as e:
            # Log the SDE error to the console but don't crash the request
            logger.error(f"ERROR: Failed during implant enrichment in api_get_implants: {e}", exc_info=True)
            # The 'enriched_implants' list will be empty or partial, which is fine.
        
        # --- END REFACTORED SDE & GROUPING LOGIC ---
        
        sorted_implants = sorted(enriched_implants, key=lambda i: i.get('slot', 0))
        
        implants_other = []
        implants_col1 = [] # Slots 1-5
        implants_col2 = [] # Slots 6-10
        for implant in sorted_implants:
            slot = implant.get('slot', 0)
            if 0 < slot <= 5:
                implants_col1.append(implant)
            elif 5 < slot <= 10:
                implants_col2.append(implant)
            else:
                implants_other.append(implant)
        
        context = {
            'implants_other': implants_other,
            'implants_col1': implants_col1,
            'implants_col2': implants_col2,
        }
        
        try:
            # Render the partial template to HTML
            html = render_to_string('_implant_list.html', context)
        except Exception as e:
            logger.error(f"Failed to render _implant_list.html: {e}", exc_info=True)
            return JsonResponse({
                "status": "error", 
                "message": f"Template rendering failed: {str(e)}"
            }, status=500)
        
        # Return the HTML and the expiry time
        logger.debug(f"Successfully served implants for {character_id} (X-Up modal)")
        return JsonResponse({
            "status": "success",
            "html": html,
            "expires_iso": expires_iso
        })

    except Exception as e:
        # This catches ESI errors, token errors, etc.
        logger.error(f"Error in api_get_implants for {character_id}: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_POST
def api_set_main_character(request):
    """
    Sets a new main character for the logged-in user.
    """
    character_id = request.POST.get('character_id')
    logger.info(f"User {request.user.username} setting main character to {character_id}")
    if not character_id:
        logger.warning(f"api_set_main_character: Missing character_id")
        return JsonResponse({"status": "error", "message": "Missing character_id."}, status=400)
        
    try:
        with transaction.atomic():
            # 1. Get the character to set as main
            new_main = EveCharacter.objects.get(
                character_id=character_id,
                user=request.user # Ensure it belongs to this user
            )
            
            # 2. Unset all other mains for this user
            request.user.eve_characters.exclude(
                character_id=character_id
            ).update(is_main=False)
            
            # 3. Set the new main
            new_main.is_main = True
            new_main.save()
            
            logger.info(f"User {request.user.username} successfully set {new_main.character_name} as main")
            return JsonResponse({"status": "success", "message": f"{new_main.character_name} is now your main character."})

    except EveCharacter.DoesNotExist:
        logger.warning(f"api_set_main_character: User {request.user.username} tried to set non-existent/unowned char {character_id}")
        return JsonResponse({"status": "error", "message": "Character not found or does not belong to you."}, status=404)
    except Exception as e:
        logger.error(f"Error in api_set_main_character: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(e)}, status=500)