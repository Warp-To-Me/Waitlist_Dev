from django.contrib import admin
# Import the models that *actually exist* from waitlist.models
from waitlist.models import EveCharacter, ShipFit, Fleet, FleetWaitlist 

# We will control FC/Admin permissions via Django's User/Group system,
# so we don't need a separate FleetCommander model registration for now.

@admin.register(EveCharacter)
class EveCharacterAdmin(admin.ModelAdmin):
    """
    Admin view for EVE Characters.
    """
    list_display = ('character_name', 'character_id', 'user')
    search_fields = ('character_name', 'user__username')

@admin.register(ShipFit)
class ShipFitAdmin(admin.ModelAdmin):
    """
    Admin view for submitted Ship Fits.
    This is where FCs will approve/deny fits.
    """
    list_display = ('character', 'get_fit_summary', 'status', 'submitted_at', 'waitlist')
    list_filter = ('status', 'submitted_at', 'waitlist')
    search_fields = ('character__character_name',)
    
    # Make status and denial_reason editable from the list view
    list_editable = ('status',)
    
    # Add fields to the detail view
    # --- FIX: Make the new fields read-only for now ---
    readonly_fields = (
        'character', 'raw_fit', 'submitted_at', 'last_updated', 'waitlist',
        'ship_name', 'tank_type', 'fit_issues', 'total_fleet_hours', 'hull_fleet_hours'
    )
    
    fieldsets = (
        (None, {
            'fields': ('character', 'status', 'denial_reason', 'waitlist')
        }),
        ('Fit Details', {
            'classes': ('collapse',), # Make this section collapsible
            'fields': ('raw_fit', 'submitted_at', 'last_updated')
        }),
        # --- NEW: Read-only section for parsed data ---
        ('Parsed Data', {
            'classes': ('collapse',),
            'fields': (
                'ship_name', 'tank_type', 'fit_issues', 
                'total_fleet_hours', 'hull_fleet_hours'
            )
        }),
    )
    # --- END FIX ---

    # Add custom actions to the admin
    actions = ['approve_fits', 'deny_fits']

    def get_fit_summary(self, obj):
        """Returns the first line of the raw_fit, usually the ship name."""
        try:
            return obj.raw_fit.splitlines()[0]
        except (IndexError, AttributeError):
            return "Empty Fit"
    get_fit_summary.short_description = "Fit Summary"

    def approve_fits(self, request, queryset):
        queryset.update(status='APPROVED', denial_reason=None)
    approve_fits.short_description = "Approve selected fits"

    def deny_fits(self, request, queryset):
        queryset.update(status='DENIED', denial_reason="Fit does not meet doctrine.")
    deny_fits.short_description = "Deny selected fits (default reason)"

@admin.register(Fleet)
class FleetAdmin(admin.ModelAdmin): # Corrected this line (removed extra .admin)
    """
    Admin view for managing active Fleets.
    """
    list_display = ('description', 'fleet_commander', 'esi_fleet_id', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('description', 'fleet_commander__character_name')

@admin.register(FleetWaitlist)
class FleetWaitlistAdmin(admin.ModelAdmin):
    """
    Admin view for managing Fleet Waitlists.
    """
    list_display = ('fleet', 'is_open', 'get_approved_count')
    list_filter = ('is_open',)
    
    # --- REMOVED ---
    # filter_horizontal = ('approved_fits',)

    def get_approved_count(self, obj):
        # --- UPDATED: Use new related name ---
        return obj.all_fits.filter(status='APPROVED').count()
    get_approved_count.short_description = "Approved Fits"