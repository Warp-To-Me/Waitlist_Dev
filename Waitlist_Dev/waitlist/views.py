import logging
import json
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.utils import timezone
from .models import EveCharacter, ShipFit, FleetWaitlist, DoctrineFit
from pilot.models import EveType
from .fit_parser import parse_eft_fit, check_fit_against_doctrines
from .helpers import is_fleet_commander  # Import from new helper file

# Get a logger for this specific Python file
logger = logging.getLogger(__name__)


@login_required
def home(request):
    """
    Handles the main homepage (/).
    - If user is authenticated, shows the waitlist_view.
    - If not, shows the simple login page (homepage.html).
    """
    
    logger.debug(f"User {request.user.username} accessing home view")
    
    if not request.user.is_authenticated:
        # User is not logged in, show the simple homepage
        logger.debug("User is not authenticated, showing public homepage.html")
        return render(request, 'homepage.html')

    # User is logged in, show the waitlist view
    logger.debug("User is authenticated, preparing waitlist_view.html")
    
    # 1. Find the currently open waitlist (or return None)
    open_waitlist = FleetWaitlist.objects.filter(is_open=True).first()
    
    # 2. Get all fits for the open waitlist
    all_fits = []
    if open_waitlist:
        logger.debug(f"Open waitlist found: {open_waitlist.fleet.description}")
        all_fits = ShipFit.objects.filter(
            waitlist=open_waitlist,
            status__in=['PENDING', 'APPROVED'] # Don't show IN_FLEET pilots
        ).select_related('character').order_by('submitted_at') # Order by time
    else:
        logger.debug("No open waitlist found.")

    # Sort fits into categories
    xup_fits = all_fits.filter(status='PENDING') if open_waitlist else []
    dps_fits = all_fits.filter(status='APPROVED', category__in=['DPS', 'MAR_DPS']) if open_waitlist else []
    logi_fits = all_fits.filter(status='APPROVED', category='LOGI') if open_waitlist else []
    sniper_fits = all_fits.filter(status='APPROVED', category__in=['SNIPER', 'MAR_SNIPER']) if open_waitlist else []
    other_fits = all_fits.filter(status='APPROVED', category='OTHER') if open_waitlist else []
    
    is_fc = is_fleet_commander(request.user) # Use helper
    
    # Get character info for header and modals
    all_user_chars = request.user.eve_characters.all().order_by('character_name')
    main_char = all_user_chars.filter(is_main=True).first()
    if not main_char:
        main_char = all_user_chars.first()
    
    context = {
        'xup_fits': xup_fits,
        'dps_fits': dps_fits,
        'logi_fits': logi_fits,
        'sniper_fits': sniper_fits,
        'other_fits': other_fits,
        'is_fc': is_fc,
        'open_waitlist': open_waitlist,
        'user_characters': all_user_chars, # For the X-Up modal
        'all_chars_for_header': all_user_chars, # For header dropdown
        'main_char_for_header': main_char, # For header dropdown
    }
    return render(request, 'waitlist_view.html', context)
    

@login_required
def fittings_view(request):
    """
    Displays all available doctrine fits for all users to see.
    """
    logger.debug(f"User {request.user.username} accessing fittings_view")
    
    # 1. Define the category order and display names
    categories_map = {
        'LOGI': {'name': 'Logi', 'fits': []},
        'DPS': {'name': 'DPS', 'fits': []},
        'SNIPER': {'name': 'Sniper', 'fits': []},
        'MAR_DPS': {'name': 'MAR DPS', 'fits': []},
        'MAR_SNIPER': {'name': 'MAR Sniper', 'fits': []},
        'OTHER': {'name': 'Other', 'fits': []},
    }

    # 2. Get all fits, ordered correctly
    all_fits_list = DoctrineFit.objects.all().select_related('ship_type').order_by('category', 'name')
    logger.debug(f"Found {all_fits_list.count()} total doctrine fits")
    
    # 3. Sort fits into the map
    for fit in all_fits_list:
        if fit.category in categories_map:
            categories_map[fit.category]['fits'].append(fit)
        elif fit.category != 'NONE':
            # Fallback for any other categories
            if 'OTHER' not in categories_map:
                categories_map['OTHER'] = {'name': 'Other', 'fits': []}
            categories_map['OTHER']['fits'].append(fit)

    # 4. Create a final list, filtering out empty categories
    grouped_fits = [data for data in categories_map.values() if data['fits']]

    # 5. Get context variables needed by base.html
    is_fc = is_fleet_commander(request.user) # Use helper
    
    all_user_chars = request.user.eve_characters.all().order_by('character_name')
    main_char = all_user_chars.filter(is_main=True).first()
    if not main_char:
        main_char = all_user_chars.first()
    
    context = {
        'grouped_fits': grouped_fits,
        'is_fc': is_fc,
        'user_characters': all_user_chars, # For X-Up modal
        'all_chars_for_header': all_user_chars, # For header dropdown
        'main_char_for_header': main_char, # For header dropdown
    }
    
    return render(request, 'fittings_view.html', context)


@login_required
@require_POST
def api_submit_fit(request):
    """
    Handles the fit submission from the X-Up modal.
    """
    open_waitlist = FleetWaitlist.objects.filter(is_open=True).first()
    logger.debug(f"User {request.user.username} attempting fit submission")

    if not open_waitlist:
        logger.warning(f"Fit submission failed for {request.user.username}: Waitlist is closed")
        return JsonResponse({"status": "error", "message": "The waitlist is currently closed."}, status=400)

    # Get data from the form
    character_id = request.POST.get('character_id')
    raw_fit_original = request.POST.get('raw_fit') 
    
    # Validate that the character belongs to the user
    try:
        character = EveCharacter.objects.get(
            character_id=character_id, 
            user=request.user
        )
    except EveCharacter.DoesNotExist:
        logger.warning(f"Fit submission failed: User {request.user.username} submitted for char {character_id} which they don't own")
        return JsonResponse({"status": "error", "message": "Invalid character selected."}, status=403)
    
    if not raw_fit_original:
        logger.warning(f"Fit submission failed for {character.character_name}: Fit was empty")
        return JsonResponse({"status": "error", "message": "Fit cannot be empty."}, status=400)
    
    try:
        # 1. Call the centralized parser
        logger.debug(f"Parsing fit for {character.character_name}")
        ship_type, parsed_fit_list, fit_summary_counter = parse_eft_fit(raw_fit_original)
        ship_type_id = ship_type.type_id
        logger.debug(f"Fit parsed successfully: {ship_type.name}")

        # 2. Check for Auto-Approval
        logger.debug(f"Checking {ship_type.name} against doctrines")
        doctrine, new_status, new_category = check_fit_against_doctrines(
            ship_type_id,
            dict(fit_summary_counter)
        )
        if doctrine:
            logger.info(f"Fit for {character.character_name} matched doctrine {doctrine.name}. Status: {new_status}")
        else:
            logger.info(f"Fit for {character.character_name} did not match doctrine. Status: {new_status}")

        # 3. Save to database
        fit, created = ShipFit.objects.update_or_create(
            character=character,
            waitlist=open_waitlist,
            status__in=['PENDING', 'APPROVED'], # Find any existing fit
            defaults={
                'raw_fit': raw_fit_original,  # Save the *original* fit
                'parsed_fit_json': json.dumps(parsed_fit_list), # Save the parsed data
                'status': new_status, # 'PENDING' or 'APPROVED'
                'waitlist': open_waitlist,
                'ship_name': ship_type.name,
                'ship_type_id': ship_type_id,
                'tank_type': 'Shield',        # <-- Placeholder
                'fit_issues': None,           # <-- Placeholder
                'category': new_category,     # 'NONE' or from doctrine
                'submitted_at': timezone.now(),
                'last_updated': timezone.now(), # Force update timestamp
            }
        )
        
        if created:
            logger.info(f"New fit {fit.id} created for {character.character_name}")
            return JsonResponse({"status": "success", "message": f"Fit for {character.character_name} submitted!"})
        else:
            logger.info(f"Fit {fit.id} updated for {character.character_name}")
            return JsonResponse({"status": "success", "message": f"Fit for {character.character_name} updated."})

    except ValueError as e:
        # Catch parsing errors raised from parse_eft_fit
        logger.warning(f"Fit parsing failed for {character.character_name}: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
    except Exception as e:
        # Catch other unexpected issues
        logger.error(f"Unexpected error in api_submit_fit for {character.character_name}: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": f"An unexpected error occurred: {str(e)}"}, status=500)


@login_required
@require_POST
def api_update_fit_status(request):
    """
    Handles FC actions (approve/deny) from the waitlist view.
    """
    if not is_fleet_commander(request.user): # Use helper
        logger.warning(f"Non-FC user {request.user.username} tried to update fit status")
        return JsonResponse({"status": "error", "message": "Not authorized"}, status=403)

    fit_id = request.POST.get('fit_id')
    action = request.POST.get('action')
    logger.info(f"FC {request.user.username} performing action '{action}' on fit {fit_id}")

    try:
        fit = ShipFit.objects.get(id=fit_id)
    except ShipFit.DoesNotExist:
        logger.warning(f"FC {request.user.username} tried to {action} non-existent fit {fit_id}")
        return JsonResponse({"status": "error", "message": "Fit not found"}, status=404)

    if action == 'approve':
        fit.status = 'APPROVED'
        
        if fit.category == ShipFit.FitCategory.NONE:
            fit.category = ShipFit.FitCategory.OTHER
            logger.debug(f"Fit {fit.id} approved, category set to OTHER")
        
        fit.save()
        logger.info(f"Fit {fit.id} ({fit.character.character_name}) approved by {request.user.username}")
        return JsonResponse({"status": "success", "message": "Fit approved"})
        
    elif action == 'deny':
        fit.status = 'DENIED'
        fit.denial_reason = "Denied by FC from waitlist."
        fit.save()
        logger.info(f"Fit {fit.id} ({fit.character.character_name}) denied by {request.user.username}")
        return JsonResponse({"status": "success", "message": "Fit denied"})

    logger.warning(f"FC {request.user.username} sent invalid action '{action}' for fit {fit_id}")
    return JsonResponse({"status": "error", "message": "Invalid action"}, status=400)


@login_required
def api_get_waitlist_html(request):
    """
    Returns just the HTML for the waitlist columns.
    Used by the live polling JavaScript.
    """
    # This view is polled every 5s, so we use DEBUG level
    logger.debug(f"Polling request received from {request.user.username}")
    
    open_waitlist = FleetWaitlist.objects.filter(is_open=True).first()
    
    if not open_waitlist:
        logger.debug("Polling request: Waitlist is closed")
        return HttpResponseBadRequest("Waitlist closed")

    all_fits = ShipFit.objects.filter(
        waitlist=open_waitlist,
        status__in=['PENDING', 'APPROVED']
    ).select_related('character').order_by('submitted_at')

    xup_fits = all_fits.filter(status='PENDING')
    dps_fits = all_fits.filter(status='APPROVED', category__in=['DPS', 'MAR_DPS'])
    logi_fits = all_fits.filter(status='APPROVED', category='LOGI')
    sniper_fits = all_fits.filter(status='APPROVED', category__in=['SNIPER', 'MAR_SNIPER'])
    other_fits = all_fits.filter(status='APPROVED', category='OTHER')
    
    is_fc = is_fleet_commander(request.user) # Use helper

    context = {
        'xup_fits': xup_fits,
        'dps_fits': dps_fits,
        'logi_fits': logi_fits,
        'sniper_fits': sniper_fits,
        'other_fits': other_fits,
        'is_fc': is_fc,
    }
    
    logger.debug(f"Polling response: XUP:{xup_fits.count()}, LOGI:{logi_fits.count()}, DPS:{dps_fits.count()}, SNIPER:{sniper_fits.count()}, OTHER:{other_fits.count()}")
    return render(request, '_waitlist_columns.html', context)