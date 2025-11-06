from django.db import models
from django.conf import settings

# Create your models here.

class EveCharacter(models.Model):
    """
    Stores EVE Online character data linked to a Django user.
    """
    # This links the EVE character to a user in Django's built-in auth system.
    # A User can have multiple EVE characters.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="eve_characters"
    )
    character_id = models.BigIntegerField(unique=True, primary_key=True)
    character_name = models.CharField(max_length=255)

    # ESI token information
    # We encrypt these in a real app, but store as text for this example.
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField()

    def __str__(self):
        return self.character_name

class Fleet(models.Model):
    """
    Represents a fleet that a character can be invited to.
    Managed by FCs.
    """
    fleet_commander = models.ForeignKey(
        EveCharacter,
        on_delete=models.PROTECT, # Don't delete a fleet just because an FC is deleted
        related_name="commanded_fleets"
    )
    esi_fleet_id = models.BigIntegerField(unique=True, help_text="The ESI ID of the active fleet.")
    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Fleet {self.esi_fleet_id} ({self.fleet_commander.character_name})"

class FleetWaitlist(models.Model):
    """
    A specific waitlist for a specific fleet.
    This links a Fleet to a list of approved ShipFits.
    """
    fleet = models.OneToOneField(
        Fleet,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="waitlist" # Add related_name
    )
    is_open = models.BooleanField(default=True)

    def __str__(self):
        return f"Waitlist for {self.fleet.description}"


class ShipFit(models.Model):
    """
    Represents a single ship fit submitted to the waitlist.
    """
    class FitStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        DENIED = 'DENIED', 'Denied'
        IN_FLEET = 'IN_FLEET', 'In Fleet' # Not used yet, but good to have

    # --- NEW: Category Choices ---
    # This will be used for sorting into columns
    class FitCategory(models.TextChoices):
        NONE = 'NONE', 'None'
        DPS = 'DPS', 'DPS'
        LOGI = 'LOGI', 'Logi'
        SNIPER = 'SNIPER', 'Sniper'
        MAR_DPS = 'MAR_DPS', 'MAR DPS'
        MAR_SNIPER = 'MAR_SNIPER', 'MAR Sniper'

    # --- UPDATED: Link to the Waitlist directly ---
    waitlist = models.ForeignKey(
        FleetWaitlist,
        on_delete=models.CASCADE,
        related_name="all_fits",
        null=True, # Allow fits to exist without a waitlist (for history)
        blank=True
    )
    
    # The character who submitted this fit
    character = models.ForeignKey(
        EveCharacter,
        on_delete=models.CASCADE,
        related_name="submitted_fits"
    )
    
    # The raw fit string (EFT format or similar) pasted by the user
    raw_fit = models.TextField(help_text="The ship fit in EFT (or similar) format.")
    
    # Status of the fit in the waitlist
    status = models.CharField(
        max_length=10,
        choices=FitStatus.choices,
        default=FitStatus.PENDING,
        db_index=True # Good to index this for fast filtering
    )

    # Reason for denial, to be filled in by an FC
    denial_reason = models.TextField(blank=True, null=True)

    # Timestamps
    submitted_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    # --- NEW FIELDS for parsed data (placeholders) ---
    # These will be filled by the fit_parser later
    
    ship_name = models.CharField(max_length=255, null=True, blank=True)
    ship_type_id = models.BigIntegerField(null=True, blank=True) # --- ADDED FOR IMAGE ---
    tank_type = models.CharField(max_length=50, null=True, blank=True)
    fit_issues = models.TextField(null=True, blank=True)
    
    # --- NEW: Category for sorting ---
    category = models.CharField(
        max_length=20,
        choices=FitCategory.choices,
        default=FitCategory.NONE,
        db_index=True
    )

    # These are placeholders for future ESI tracking
    total_fleet_hours = models.IntegerField(default=0)
    hull_fleet_hours = models.IntegerField(default=0)
    # --- END NEW FIELDS ---

    def __str__(self):
        return f"{self.character.character_name} - {self.ship_name} ({self.status})"