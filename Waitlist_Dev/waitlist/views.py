from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.contrib import messages
from .models import EveCharacter, ShipFit, Fleet, FleetWaitlist
from django.utils import timezone # Import timezone

# Create your views here.

@login_required
def home(request):
    """
    Handles the main homepage (/).
    - If user is authenticated, shows the waitlist_view.
    - If not, shows the x-up form (homepage.html).
    """
    
    # --- UPDATED GET LOGIC ---
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

    # --- TODO: Replace this placeholder sorting ---
    xup_fits = all_fits.filter(status='PENDING') if open_waitlist else []
    dps_fits = all_fits.filter(status='APPROVED', ship_name='Vargur') if open_waitlist else []
    logi_fits = all_fits.filter(status='APPROVED', ship_name='Logi') if open_waitlist else []
    sniper_fits = all_fits.filter(status='APPROVED', ship_name='Sniper') if open_waitlist else []
    
    context = {
        'xup_fits': xup_fits,
        'dps_fits': dps_fits,
        'logi_fits': logi_fits,
        'sniper_fits': sniper_fits,
        'is_fc': request.user.is_staff, # Pass FC status to template
        'open_waitlist': open_waitlist,
        'user_characters': EveCharacter.objects.filter(user=request.user) # For the modal
    }
    return render(request, 'waitlist_view.html', context)
    
    # --- POST LOGIC HAS BEEN MOVED TO 'api_submit_fit' ---


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

    # Use update_or_create to handle new vs. updated fits
    fit, created = ShipFit.objects.update_or_create(
        character=character,
        waitlist=open_waitlist,
        status__in=['PENDING', 'APPROVED', 'IN_FLEET'],
        defaults={
            'raw_fit': raw_fit,
            'status': 'PENDING', # Reset status to PENDING on update
            'waitlist': open_waitlist,
            'ship_name': 'Vargur', # Placeholder
            'ship_type_id': 12011,   # Placeholder (Vargur Type ID)
            'tank_type': 'Shield', # Placeholder
            'fit_issues': None,
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
    if not request.user.is_staff:
        return JsonResponse({"status": "error", "message": "Not authorized"}, status=403)

    fit_id = request.POST.get('fit_id')
    action = request.POST.get('action')

    try:
        fit = ShipFit.objects.get(id=fit_id)
    except ShipFit.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Fit not found"}, status=404)

    if action == 'approve':
        fit.status = 'APPROVED'
        # --- UPDATED: Add placeholder ship_name and ship_type_id ---
        fit.ship_name = "Vargur"   # <-- Placeholder
        fit.ship_type_id = 12011     # <-- Placeholder (Vargur Type ID)
        fit.tank_type = "Shield" # <-- Placeholder
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
    
    # 1. Find the currently open waitlist (or return None)
    open_waitlist = FleetWaitlist.objects.filter(is_open=True).first()
    
    if not open_waitlist:
        # If waitlist closed, send back empty HTML
        return HttpResponseBadRequest("Waitlist closed")

    # 2. Get all fits for the open waitlist
    all_fits = ShipFit.objects.filter(
        waitlist=open_waitlist,
        status__in=['PENDING', 'APPROVED', 'IN_FLEET']
    ).select_related('character').order_by('submitted_at') # Order by time

    # --- TODO: Replace this placeholder sorting ---
    xup_fits = all_fits.filter(status='PENDING')
    dps_fits = all_fits.filter(status='APPROVED', ship_name='Vargur') # Placeholder
    logi_fits = all_fits.filter(status='APPROVED', ship_name='Logi') # Placeholder
    sniper_fits = all_fits.filter(status='APPROVED', ship_name='Sniper') # Placeholder
    
    context = {
        'xup_fits': xup_fits,
        'dps_fits': dps_fits,
        'logi_fits': logi_fits,
        'sniper_fits': sniper_fits,
        'is_fc': request.user.is_staff,
    }
    
    # --- FIX: Render the template from its new, simpler path ---
    return render(request, '_waitlist_columns.html', context)