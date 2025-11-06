from django.shortcuts import render, get_object_or_404, redirect, resolve_url
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
import json

from waitlist.models import EveCharacter
from .models import PilotSnapshot, EveGroup, EveType

# Import the ESI client and token helpers
from esi.clients import EsiClientProvider
from esi.decorators import token_required
from esi.models import Token

# --- THIS IS THE FIX (Part 1) ---
# We REMOVE the line 'esi = EsiClientProvider()' from here.
# It was crashing the server on startup.
# --- END FIX ---


@login_required
def pilot_detail(request, character_id):
    """
    Displays the skills and implants for a specific character.
    """
    
    # --- THIS IS THE FIX (Part 2) ---
    # We move the client initialization INSIDE the view.
    # It will now run safely when the view is called.
    esi = EsiClientProvider()
    # --- END FIX ---

    character = get_object_or_404(EveCharacter, character_id=character_id, user=request.user)
    
    # Manually fetch the token for this character and user
    try:
        # We replace .order_by('-expires') with .order_by('-created')
        # to sort by the 'created' field, which exists.
        token = Token.objects.filter(
            user=request.user, 
            character_id=character_id
        ).order_by('-created').first() # <-- This fix is already in your file
        
        # If .first() returns None, it means no token exists.
        if not token:
            raise Token.DoesNotExist

    except Token.DoesNotExist:
        # The user has no token for this character.
        # Send them to the login page to add/refresh this character.
        return redirect('esi_auth:login')

    # --- THIS IS THE FIX ---
    # Manually check if the token has the scopes we need
    required_scopes = ['esi-skills.read_skills.v1', 'esi-clones.read_implants.v1']
    
    if not token.scopes:
        # Token has no scopes at all.
        return redirect(f"{resolve_url('esi_auth:login')}?scopes=regular")
        
    # 'token.scopes' is a ManyRelatedManager. We must query it.
    # We will get all related scope objects and extract their 'name' field.
    available_scopes = set(s.name for s in token.scopes.all())
    
    # Check if all required scopes are in the available set.
    has_all_scopes = all(scope in available_scopes for scope in required_scopes)

    if not has_all_scopes:
        # The token exists but is missing scopes.
        # Send them to the login page to re-authorize.
        return redirect(f"{resolve_url('esi_auth:login')}?scopes=regular")
    # --- END FIX ---


    # Get the snapshot from the DB, or create one if it doesn't exist
    snapshot, created = PilotSnapshot.objects.get_or_create(character=character)
    
    needs_update = False
    if created or snapshot.last_updated < (timezone.now() - timedelta(hours=1)):
        # Update if it's new or older than 1 hour
        needs_update = True
        
    # --- THIS IS THE FIX ---
    # We will ALSO force an update if the critical data is missing,
    # regardless of how old the snapshot is. This will force the
    # ESI call block to run.
    if not snapshot.skills_json or not snapshot.implants_json:
        needs_update = True
    # --- END FIX ---

    if needs_update:
        try:
            # Fetch fresh data from ESI
            # We now use our manually-fetched 'token' object
            skills_response = esi.client.Skills.get_characters_character_id_skills(
                character_id=character_id,
                token=token.access_token
            ).results()

            # --- THIS IS THE FIX ---
            # We were missing the ESI call to get implants.
            implants_response = esi.client.Clones.get_characters_character_id_implants(
                character_id=character_id,
                token=token.access_token
            ).results()
            # --- END FIX ---


            # --- THIS IS THE FIX ---
            # We must check if the response is valid before saving it.
            # If the token is bad, ESI returns an error JSON, not an exception.
            if 'skills' not in skills_response or 'total_sp' not in skills_response:
                # This is not a valid skill response.
                # We will manually raise an error to force a token refresh.
                raise Exception(f"Invalid skills response: {skills_response}")
                
            if not isinstance(implants_response, list):
                # This is not a valid implant response
                raise Exception(f"Invalid implants response: {implants_response}")
            # --- END FIX ---

            # If we get here, the data is valid.
            snapshot.skills_json = json.dumps(skills_response)
            snapshot.implants_json = json.dumps(implants_response)
            snapshot.save()
            
            # The 'snapshot' variable is now stale.
            # Re-load it from the database
            snapshot.refresh_from_db()

        except Exception as e:
            # --- THIS IS THE FIX ---
            # The ESI call is failing, but 'pass' was hiding the error.
            # We will now re-raise the exception so we can see what's
            # really going on.
            raise e
            # --- END FIX ---
            
    # --- NEW SDE & GROUPING LOGIC ---

    # This is our final structure: {"Gunnery": [{"name": "Small Autocannon", "level": 5}, ...]}
    grouped_skills = {}

    # 1. Get the raw skill list from the (now fresh) snapshot
    skills_list = snapshot.get_skills()
    
    if skills_list:
        all_skill_ids = [s['skill_id'] for s in skills_list]
        
        # 2. Find all skills we *already* have in our local DB
        cached_types = {t.type_id: t for t in EveType.objects.filter(type_id__in=all_skill_ids).select_related('group')}
        
        # 3. Find all skill IDs we *don't* have
        missing_skill_ids = [sid for sid in all_skill_ids if sid not in cached_types]
        
        newly_cached_types = []

        # 4. This is the slow part.
        if missing_skill_ids:
            # We also need to cache any new groups
            cached_groups = {g.group_id: g for g in EveGroup.objects.all()}
            
            for skill_id in missing_skill_ids:
                try:
                    # A. Fetch the Type (skill) info
                    type_data = esi.client.Universe.get_universe_types_type_id(type_id=skill_id).results()
                    
                    group_id = type_data['group_id']
                    group = None
                    
                    # B. Fetch or create the Group (category) info
                    if group_id in cached_groups:
                        group = cached_groups[group_id]
                    else:
                        # We don't have this group, fetch it
                        group_data = esi.client.Universe.get_universe_groups_group_id(group_id=group_id).results()
                        group = EveGroup.objects.create(
                            group_id=group_id,
                            name=group_data['name']
                        )
                        cached_groups[group.group_id] = group # Add to our cache
                        
                    # C. Create the new EveType object
                    new_type = EveType.objects.create(
                        type_id=skill_id,
                        name=type_data['name'],
                        group=group
                    )
                    newly_cached_types.append(new_type)
                    
                except Exception as e:
                    # ESI error, just skip this skill
                    continue
                        
        # 5. Merge the newly cached types into our 'cached_types' dict
        for t in newly_cached_types:
            cached_types[t.type_id] = t
            
        # 6. Now, build the final grouped_skills dictionary
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
        
    # 7. Sort the dictionary by group name for a clean look
    sorted_grouped_skills = dict(sorted(grouped_skills.items()))

    # --- END NEW SDE LOGIC ---

    context = {
        'character': character,
        'implants': snapshot.get_implants(),
        'total_sp': snapshot.get_total_sp(),
        'snapshot_time': snapshot.last_updated,
        'portrait_url': f"https://images.evetech.net/characters/{character.character_id}/portrait?size=256",
        'grouped_skills': sorted_grouped_skills, # Pass the new dict
    }
    
    return render(request, 'pilot_detail.html', context)