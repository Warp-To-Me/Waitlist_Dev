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
    list_display = ('character', 'get_fit_summary', 'status', 'submitted_at')
    list_filter = ('status', 'submitted_at')
    search_fields = ('character__character_name',)
    
    # Make status and denial_reason editable from the list view
    list_editable = ('status',)
    
    # Add fields to the detail view
    readonly_fields = ('submitted_at', 'last_updated')
    fieldsets = (
        (None, {
            'fields': ('character', 'status', 'denial_reason')
        }),
        ('Fit Details', {
            'fields': ('raw_fit', 'submitted_at', 'last_updated')
        }),
    )

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
    
    # This allows adding/removing fits from a waitlist in the admin
    # This is how you'd manually add an approved fit to a waitlist.
    filter_horizontal = ('approved_fits',)

    def get_approved_count(self, obj):
        return obj.approved_fits.count()
    get_approved_count.short_description = "Approved Fits"


