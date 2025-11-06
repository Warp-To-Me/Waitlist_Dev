from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.contrib import messages
from .models import EveCharacter, ShipFit, Fleet, FleetWaitlist
from pilot.models import EveType # --- NEW: Import EveType for SDE lookup ---
from django.utils import timezone # Import timezone
import random
import eveparse # --- NEW: Import eveparse ---

# Create your views here.

@login_required
def home(request):
    """
    Handles the main homepage (/).
    - If user is authenticated, shows the waitlist_view.
    - If not, shows the simple login page (homepage.html).
    """
    
    if not request.user.is_authenticated:
        # User is not logged in, show the simple homepage
        return render(request, 'homepage.html')

    # User is logged in, show the waitlist view
    
    # 1. Find the currently open waitlist (or return None)
    open_waitlist = FleetWaitlist.objects.filter(is_open=True).first()
    
    # 2. Get all fits for the open waitlist
    all_fits = []
    if open_waitlist:
        all_fits = ShipFit.objects.filter(
            waitlist=open_waitlist,
            status__in=['PENDING', 'APPROVED', 'IN_FLEET']
        ).select_related('character').order_by('submitted_at') # Order by time

    # --- UPDATED: Sorting now uses the new 'category' field ---
    xup_fits = all_fits.filter(status='PENDING') if open_waitlist else []
    dps_fits = all_fits.filter(status='APPROVED', category='DPS') if open_waitlist else []
    logi_fits = all_fits.filter(status='APPROVED', category='LOGI') if open_waitlist else []
    sniper_fits = all_fits.filter(status='APPROVED', category='SNIPER') if open_waitlist else []
    mar_dps_fits = all_fits.filter(status='APPROVED', category='MAR_DPS') if open_waitlist else []
    mar_sniper_fits = all_fits.filter(status='APPROVED', category='MAR_SNIPER') if open_waitlist else []
    
    is_fc = request.user.groups.filter(name='Fleet Commander').exists()
    
    context = {
        'xup_fits': xup_fits,
        'dps_fits': dps_fits,
        'logi_fits': logi_fits,
        'sniper_fits': sniper_fits,
        'mar_dps_fits': mar_dps_fits,
        'mar_sniper_fits': mar_sniper_fits,
        'is_fc': is_fc, # Pass FC status to template
        'open_waitlist': open_waitlist,
        'user_characters': EveCharacter.objects.filter(user=request.user) # For the modal
    }
    return render(request, 'waitlist_view.html', context)
    

# --- NEW API VIEW for Modal Fit Submission ---
@login_required
@require_POST
def api_submit_fit(request):
    """
    Handles the fit submission from the X-Up modal.
    """
    open_waitlist = FleetWaitlist.objects.filter(is_open=True).first()

    if not open_waitlist:
        return JsonResponse({"status": "error", "message": "The waitlist is currently closed."}, status=400)

    # Get data from the form
    character_id = request.POST.get('character_id')
    raw_fit = request.POST.get('raw_fit')
    
    # Validate that the character belongs to the user
    try:
        character = EveCharacter.objects.get(
            character_id=character_id, 
            user=request.user
        )
    except EveCharacter.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Invalid character selected."}, status=403)
    
    if not raw_fit:
        return JsonResponse({"status": "error", "message": "Fit cannot be empty."}, status=400)

    # --- NEW: Parse the fit to get the ship hull ---
    try:
        # eveparse returns a (ship_name, items) tuple
        ship_name, items = eveparse.parse_single(raw_fit)
        if not ship_name:
            raise eveparse.ParserError("Could not determine ship hull.")
            
        # Now, get the Type ID from our SDE model (pilot.models.EveType)
        ship_type = EveType.objects.filter(name=ship_name).first()
        
        if not ship_type:
            # We don't have this ship cached.
            # For now, we'll deny, but later we can fetch it from ESI
            return JsonResponse({"status": "error", "message": f"Ship hull '{ship_name}' not found in SDE cache. Please ask an admin to add it."}, status=400)
        
        ship_type_id = ship_type.type_id

    except eveparse.ParserError as e:
        return JsonResponse({"status": "error", "message": f"Fit Parse Error: {e}"}, status=400)
    except Exception:
        return JsonResponse({"status": "error", "message": "An error occurred during fit parsing."}, status=500)
    # --- END NEW PARSING LOGIC ---


    # Use update_or_create to handle new vs. updated fits
    fit, created = ShipFit.objects.update_or_create(
        character=character,
        waitlist=open_waitlist,
        status__in=['PENDING', 'APPROVED', 'IN_FLEET'],
        defaults={
            'raw_fit': raw_fit,
            'status': 'PENDING', # Reset status to PENDING on update
            'waitlist': open_waitlist,
            'ship_name': ship_name,       # <-- REAL SHIP NAME
            'ship_type_id': ship_type_id, # <-- REAL TYPE ID
            'tank_type': 'Shield',        # <-- Placeholder
            'fit_issues': None,           # <-- Placeholder
            'category': 'NONE',           # <-- Reset category on resubmit
            'submitted_at': timezone.now() # Explicitly update timestamp
        }
    )
    
    if created:
        return JsonResponse({"status": "success", "message": f"Fit for {character.character_name} submitted!"})
    else:
        return JsonResponse({"status": "success", "message": f"Fit for {character.character_name} updated."})


@login_required
@require_POST # Ensure this can only be POSTed to
def api_update_fit_status(request):
    """
    Handles FC actions (approve/deny) from the waitlist view.
    This is called by the JavaScript 'fetch' command.
    """
    if not request.user.groups.filter(name='Fleet Commander').exists():
        return JsonResponse({"status": "error", "message": "Not authorized"}, status=403)

    fit_id = request.POST.get('fit_id')
    action = request.POST.get('action')

    try:
        fit = ShipFit.objects.get(id=fit_id)
    except ShipFit.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Fit not found"}, status=404)

    if action == 'approve':
        fit.status = 'APPROVED'
        
        # --- UPDATED: Randomly assign to a 'category' for sorting ---
        # We no longer touch ship_name or tank_type here
        categories = ['DPS', 'LOGI', 'SNIPER', 'MAR_DPS', 'MAR_SNIPER']
        fit.category = random.choice(categories) # <-- Placeholder sorting
        # --- END UPDATE ---
        
        fit.save()
        return JsonResponse({"status": "success", "message": "Fit approved"})
        
    elif action == 'deny':
        fit.status = 'DENIED'
        fit.denial_reason = "Denied by FC from waitlist."
        fit.save()
        return JsonResponse({"status": "success", "message": "Fit denied"})

    return JsonResponse({"status": "error", "message": "Invalid action"}, status=400)


# --- NEW API VIEW ---
@login_required
def api_get_waitlist_html(request):
    """
    Returns just the HTML for the waitlist columns.
    Used by the live polling JavaScript.
    """
    
    open_waitlist = FleetWaitlist.objects.filter(is_open=True).first()
    
    if not open_waitlist:
        return HttpResponseBadRequest("Waitlist closed")

    all_fits = ShipFit.objects.filter(
        waitlist=open_waitlist,
        status__in=['PENDING', 'APPROVED', 'IN_FLEET']
    ).select_related('character').order_by('submitted_at') # Order by time

    # --- UPDATED: Sorting now uses the new 'category' field ---
    xup_fits = all_fits.filter(status='PENDING')
    dps_fits = all_fits.filter(status='APPROVED', category='DPS')
    logi_fits = all_fits.filter(status='APPROVED', category='LOGI')
    sniper_fits = all_fits.filter(status='APPROVED', category='SNIPER')
    mar_dps_fits = all_fits.filter(status='APPROVED', category='MAR_DPS')
    mar_sniper_fits = all_fits.filter(status='APPROVED', category='MAR_SNIPER')
    
    is_fc = request.user.groups.filter(name='Fleet Commander').exists()

    context = {
        'xup_fits': xup_fits,
        'dps_fits': dps_fits,
        'logi_fits': logi_fits,
        'sniper_fits': sniper_fits,
        'mar_dps_fits': mar_dps_fits,
        'mar_sniper_fits': mar_sniper_fits,
        'is_fc': is_fc,
    }
    
    return render(request, '_waitlist_columns.html', context)