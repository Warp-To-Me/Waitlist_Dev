from django.shortcuts import render, get_object_or_404, redirect, resolve_url
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import logout
from django.utils import timezone
from datetime import timedelta, datetime
import json
# --- MODIFICATION: Removed requests ---
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from waitlist.models import EveCharacter
from .models import PilotSnapshot, EveGroup, EveType, EveCategory
# --- MODIFICATION: Removed ESI client, Token model ---
from django.db import transaction

# --- MODIFICATION: Import bravado exceptions for the one manual call ---
from bravado.exception import (
    HTTPNotFound, HTTPForbidden, HTTPBadGateway, 
    HTTPUnauthorized, HTTPInternalServerError, HTTPGatewayTimeout
)

import logging

# --- NEW IMPORTS ---
from waitlist import esi
from waitlist.exceptions import (
    EsiException, EsiTokenAuthFailure, EsiScopeMissing, 
    EsiForbidden, EsiNotFound
)
from waitlist.helpers import is_fleet_commander
# --- END NEW IMPORTS ---

logger = logging.getLogger(__name__)


# --- MODIFICATION: Removed duplicated is_fleet_commander ---
# --- MODIFICATION: Removed get_refreshed_token_for_character ---


@login_required
def pilot_detail(request, character_id):
    """
    Displays the skills and implants for a specific character.
    This view is now FAST and only loads data from the database.
    It passes a flag to the template if a refresh is needed.
    """
    
    logger.debug(f"User {request.user.username} viewing pilot_detail for char {character_id}")
    character = get_object_or_404(EveCharacter, character_id=character_id, user=request.user)
    
    try:
        # 1. Get and refresh token, and check scopes
        token = esi.get_refreshed_token_for_character(
            character, 
            required_scopes=['esi-skills.read_skills.v1', 'esi-clones.read_implants.v1']
        )
    except EsiTokenAuthFailure as e:
        logger.warning(f"Token auth failure for {character.character_name} ({e.message}), logging user {request.user.username} out.")
        logout(request)
        return redirect('esi_auth:login')
    except EsiScopeMissing as e:
        logger.warning(f"User {request.user.username} missing scopes for {character.character_name}: {e.message}. Redirecting to login.")
        return redirect(f"{resolve_url('esi_auth:login')}?scopes=regular")
    except EsiException as e:
        logger.error(f"ESI error in pilot_detail for {character.character_name}: {e.message}")
        raise e # Let Django handle the 500 error

    # 3. Get snapshot and check if it's stale
    snapshot, created = PilotSnapshot.objects.get_or_create(character=character)
    
    needs_update = False
    if created or snapshot.last_updated < (timezone.now() - timedelta(hours=1)):
        logger.debug(f"Snapshot for {character.character_name} is stale or was just created.")
        needs_update = True
    if not snapshot.skills_json or not snapshot.implants_json:
        logger.debug(f"Snapshot for {character.character_name} is missing skill/implant data.")
        needs_update = True
        
    # SDE & GROUPING LOGIC (This is fast, it reads from our DB)
    logger.debug(f"Loading skills from snapshot for {character.character_name}")
    grouped_skills = {}
    skills_list = snapshot.get_skills()
    if skills_list:
        all_skill_ids = [s['skill_id'] for s in skills_list]
        cached_types = {t.type_id: t for t in EveType.objects.filter(type_id__in=all_skill_ids).select_related('group')}
        
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
        'needs_refresh': needs_update,
        
        'is_fc': is_fleet_commander(request.user),
        'user_characters': all_user_chars,
        'all_chars_for_header': all_user_chars,
        'main_char_for_header': main_char,
    }
    
    return render(request, 'pilot_detail.html', context)


# --- NEW HELPER FUNCTION FOR SDE CACHING ---
def _cache_missing_eve_types(type_ids_to_check: list):
    """
    Checks a list of type IDs against the local SDE (EveType table)
    and fetches any missing ones from ESI.
    --- MODIFIED: Uses central ESI service ---
    """
    if not type_ids_to_check:
        return

    logger.debug(f"Checking/caching {len(type_ids_to_check)} EveType IDs...")
    
    type_ids_set = set(type_ids_to_check)
    
    cached_type_ids = set(EveType.objects.filter(
        type_id__in=type_ids_set
    ).values_list('type_id', flat=True))
    
    missing_ids = list(type_ids_set - cached_type_ids)
    
    if not missing_ids:
        logger.debug("All EveTypes are already cached.")
        return

    logger.info(f"Found {len(missing_ids)} missing EveTypes to cache from ESI.")
    
    # --- MODIFICATION: Use new ESI service ---
    esi_client = esi.get_esi_client()
    
    cached_groups = {g.group_id: g for g in EveGroup.objects.all()}
    
    for type_id in missing_ids:
        try:
            # 1. Fetch type data from ESI
            type_data = esi.make_esi_call(
                esi_client.client.Universe.get_universe_types_type_id,
                type_id=type_id
            )
            
            # 2. Find or create its group
            group_id = type_data['group_id']
            group = cached_groups.get(group_id)
            
            if not group:
                logger.debug(f"Caching new group {group_id} for type {type_id}")
                group_data = esi.make_esi_call(
                    esi_client.client.Universe.get_universe_groups_group_id,
                    group_id=group_id
                )
                category_id = group_data.get('category_id')
                
                category = None
                if category_id:
                    try:
                        category = EveCategory.objects.get(category_id=category_id)
                    except EveCategory.DoesNotExist:
                        logger.warning(f"Could not find Category {category_id} for Group {group_id} while caching type {type_id}. This is fine if SDE is not fully imported.")
                        pass
                
                group = EveGroup.objects.create(
                    group_id=group_id, 
                    name=group_data['name'],
                    category=category,
                    published=group_data.get('published', True)
                )
                cached_groups[group.group_id] = group
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
                slot=slot,
                published=type_data.get('published', True),
                description=type_data.get('description'),
                mass=type_data.get('mass'),
                volume=type_data.get('volume'),
                capacity=type_data.get('capacity'),
                icon_id=type_data.get('icon_id'),
            )
            logger.debug(f"Cached new EveType: {type_data['name']} (ID: {type_id})")

        except EsiException as e: # Catch our custom exceptions
            logger.error(f"Failed to cache SDE for type_id {type_id}: {e.message}", exc_info=True)
            continue
        except Exception as e: # Catch other errors (e.g., DB errors)
            logger.error(f"Non-ESI error caching type_id {type_id}: {e}", exc_info=True)
            continue
    # --- END MODIFICATION ---

# --- MODIFICATION: Added @require_POST ---
@login_required
@require_POST
def api_refresh_pilot(request, character_id):
    """
    This view runs in the background to fetch and cache all
    ESI data (snapshot and SDE) for a character.
    
    MODIFIED: Now uses central ESI service and exceptions.
    """
    
    section = request.GET.get('section', 'all')
    
    logger.info(f"User {request.user.username} triggering ESI refresh for char {character_id} (section: {section})")
    
    try:
        character = get_object_or_404(EveCharacter, character_id=character_id, user=request.user)
        # --- MODIFICATION: Get client from service ---
        esi_client = esi.get_esi_client()
        
        # 1. Get snapshot
        snapshot, created = PilotSnapshot.objects.get_or_create(character=character)
        all_type_ids_to_cache = set()

        # 2a. Fetch Skills
        if section == 'all' or section == 'skills':
            logger.debug(f"Fetching /skills/ for {character_id}")
            # --- MODIFICATION: Use make_esi_call wrapper ---
            skills_response = esi.make_esi_call(
                esi_client.client.Skills.get_characters_character_id_skills,
                character=character,
                required_scopes=['esi-skills.read_skills.v1'],
                character_id=character_id
            )
            # --- END MODIFICATION ---
            if 'skills' not in skills_response or 'total_sp' not in skills_response:
                logger.error(f"Invalid skills response for {character_id}: {skills_response}")
                raise EsiException(f"Invalid skills response: {skills_response}")
            
            snapshot.skills_json = json.dumps(skills_response)
            all_type_ids_to_cache.update(s['skill_id'] for s in skills_response.get('skills', []))
            logger.info(f"Skills snapshot updated for {character_id}")

        # 2b. Fetch Implants
        if section == 'all' or section == 'implants':
            logger.debug(f"Fetching /implants/ for {character_id}")
            # --- MODIFICATION: Use make_esi_call wrapper ---
            implants_response = esi.make_esi_call(
                esi_client.client.Clones.get_characters_character_id_implants,
                character=character,
                required_scopes=['esi-clones.read_implants.v1'],
                character_id=character_id
            )
            # --- END MODIFICATION ---
            if not isinstance(implants_response, list):
                logger.error(f"Invalid implants response for {character_id}: {implants_response}")
                raise EsiException(f"Invalid implants response: {implants_response}")

            snapshot.implants_json = json.dumps(implants_response)
            all_type_ids_to_cache.update(implants_response)
            logger.info(f"Implants snapshot updated for {character_id}")

        # 2c. Fetch Public Data (Corp/Alliance)
        if section == 'all' or section == 'public':
            logger.debug(f"Fetching public data for {character_id}")
            # --- MODIFICATION: Use convenience function from ESI service ---
            public_data = esi.get_character_public_data(character_id)
            
            character.corporation_id = public_data.get('corporation_id')
            character.corporation_name = public_data.get('corporation_name')
            character.alliance_id = public_data.get('alliance_id')
            character.alliance_name = public_data.get('alliance_name')
            character.save()
            logger.info(f"Corp/Alliance data for {character_id} saved to DB")
            # --- END MODIFICATION ---

        # 3. Save the snapshot
        snapshot.save()
        
        # 4. Perform SDE Caching
        if all_type_ids_to_cache:
            _cache_missing_eve_types(list(all_type_ids_to_cache))

        logger.info(f"ESI refresh complete for {character_id} (section: {section})")
        return JsonResponse({"status": "success", "section": section})

    # --- NEW: Catch our custom exceptions ---
    except EsiTokenAuthFailure as e:
        logger.warning(f"api_refresh_pilot: Token auth failure for {character_id} ({e.message}), logging user out")
        logout(request)
        return JsonResponse({"status": "error", "message": e.message}, status=e.status_code)
    except (EsiScopeMissing, EsiForbidden, EsiNotFound) as e:
        logger.warning(f"api_refresh_pilot: ESI error for {character_id}: {e.message}")
        return JsonResponse({"status": "error", "message": e.message}, status=e.status_code)
    except EsiException as e:
        logger.error(f"Unexpected ESI error in api_refresh_pilot for {character_id}: {e.message}", exc_info=True)
        return JsonResponse({"status": "error", "message": e.message}, status=e.status_code)
    except Exception as e:
        # Catch non-ESI errors
        logger.error(f"Non-ESI error in api_refresh_pilot for {character_id}: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
    # --- END NEW ---


@login_required
def api_get_implants(request):
    """
    Fetches and returns a character's implants as HTML
    for the X-Up modal.
    --- MODIFIED: Uses central ESI service for token, but manual call for headers ---
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

    try:
        # --- MODIFICATION: Use ESI service to get token/check scopes ---
        esi_client = esi.get_esi_client()
        
        # 1. Get a valid token
        token = esi.get_refreshed_token_for_character(
            character,
            required_scopes=['esi-clones.read_implants.v1']
        )

        # 2. Make the call manually to get headers
        logger.debug(f"Fetching /implants/ for {character_id} (X-Up modal)")
        implants_op = esi_client.client.Clones.get_characters_character_id_implants(
            character_id=character_id,
            token=token.access_token
        )
        implants_response = implants_op.results()
        
        expires_str = implants_op.future.result().headers.get('Expires', [None])[0]
        # --- END MODIFICATION ---
        
        expires_dt = None
        expires_iso = None
        if expires_str:
            try:
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
            raise EsiException("Invalid implants response")

        all_implant_ids = implants_response
        enriched_implants = []
        
        try:
            if all_implant_ids:
                _cache_missing_eve_types(all_implant_ids)
                
                cached_types = {t.type_id: t for t in EveType.objects.filter(
                    type_id__in=all_implant_ids
                ).select_related('group')}

                for implant_id in all_implant_ids:
                    if implant_id in cached_types:
                        eve_type = cached_types[implant_id]
                        enriched_implants.append({
                            'name': eve_type.name,
                            'slot': eve_type.slot if eve_type.slot else 0,
                            'icon_url': f"https://images.evetech.net/types/{implant_id}/icon?size=32"
                        })
                    else:
                        logger.warning(f"EveType {implant_id} was not found in DB after caching attempt.")

        except Exception as e:
            logger.error(f"ERROR: Failed during implant enrichment in api_get_implants: {e}", exc_info=True)
        
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
            html = render_to_string('_implant_list.html', context)
        except Exception as e:
            logger.error(f"Failed to render _implant_list.html: {e}", exc_info=True)
            return JsonResponse({
                "status": "error", 
                "message": f"Template rendering failed: {str(e)}"
            }, status=500)
        
        logger.debug(f"Successfully served implants for {character_id} (X-Up modal)")
        return JsonResponse({
            "status": "success",
            "html": html,
            "expires_iso": expires_iso
        })

    # --- NEW: Catch bravado exceptions from the direct call ---
    except (HTTPNotFound, HTTPForbidden, HTTPBadGateway, HTTPUnauthorized, HTTPInternalServerError, HTTPGatewayTimeout) as e:
         logger.error(f"Bravado ESI error in api_get_implants for {character_id}: {e}", exc_info=True)
         return JsonResponse({"status": "error", "message": f"ESI Error: {e.response.text}"}, status=e.response.status_code)
    # --- Catch our custom exceptions from the token getter ---
    except EsiTokenAuthFailure as e:
        logger.warning(f"api_get_implants: Token auth failure for {character_id} ({e.message}), logging user out")
        logout(request)
        return JsonResponse({"status": "error", "message": e.message}, status=e.status_code)
    except (EsiScopeMissing, EsiException) as e: # Catch EsiScopeMissing and other EsiExceptions
        logger.warning(f"api_get_implants: ESI error for {character_id}: {e.message}")
        return JsonResponse({"status": "error", "message": e.message}, status=e.status_code)
    except Exception as e:
        # Catch non-ESI errors
        logger.error(f"Non-ESI error in api_get_implants for {character_id}: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
    # --- END NEW ---


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
            new_main = EveCharacter.objects.get(
                character_id=character_id,
                user=request.user
            )
            
            request.user.eve_characters.exclude(
                character_id=character_id
            ).update(is_main=False)
            
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