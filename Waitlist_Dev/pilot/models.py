from django.db import models
# --- REMOVED: from waitlist.models import EveCharacter ---
import json

# --- NEW MODEL: EveGroup ---
# This will store our "Skill Categories" (e.g., Gunnery, Spaceship Command)
# and also item groups (e.g., Projectile Ammo, Battleship)
class EveGroup(models.Model):
    group_id = models.IntegerField(primary_key=True, unique=True)
    name = models.CharField(max_length=255)
    # --- NEW FIELD ---
    # We will store the category ID (e.g., 6 for "Ship", 7 for "Module", 16 for "Skill")
    category_id = models.IntegerField(null=True, blank=True)
    # --- END NEW FIELD ---

    def __str__(self):
        return self.name

# --- NEW MODEL: EveType ---
# This will store our "Skill Types" (e.g., Small Autocannon)
# and also item types (e.g., Vargur, 1400mm Howitzer II)
class EveType(models.Model):
    type_id = models.IntegerField(primary_key=True, unique=True)
    name = models.CharField(max_length=255)
    group = models.ForeignKey(EveGroup, on_delete=models.CASCADE, related_name="types")
    
    # --- ADDED THIS FIELD ---
    slot = models.IntegerField(null=True, blank=True, help_text="Implant slot (if applicable)")
    
    # --- NEW: Added icon_url field ---
    icon_url = models.CharField(max_length=255, null=True, blank=True, help_text="URL for the item's icon")
    # --- END ADDITION ---

    # ---
    # --- NEW FIELDS FOR SHIP SLOTS (Dogma Attrs 12, 13, 14, 1137, 1367) ---
    # ---
    hi_slots = models.IntegerField(null=True, blank=True, help_text="Ship: High slots")
    med_slots = models.IntegerField(null=True, blank=True, help_text="Ship: Medium slots")
    low_slots = models.IntegerField(null=True, blank=True, help_text="Ship: Low slots")
    rig_slots = models.IntegerField(null=True, blank=True, help_text="Ship: Rig slots")
    subsystem_slots = models.IntegerField(null=True, blank=True, help_text="Ship: Subsystem slots")
    # ---
    # --- NEW FIELD FOR MODULE/ITEM SLOT TYPE (Dogma Attrs 125, 126, 127, 1154, 1373) ---
    # ---
    slot_type = models.CharField(
        max_length=10, 
        null=True, 
        blank=True, 
        db_index=True, 
        help_text="Module: 'high', 'mid', 'low', 'rig', 'subsystem', or 'drone'"
    )
    # ---
    # --- END NEW FIELDS
    # ---


    def __str__(self):
        return self.name
# --- END NEW MODELS ---


class PilotSnapshot(models.Model):
    """
    Stores a snapshot of a character's skills and implants.
    This avoids us having to store millions of individual skill records.
    We can just fetch the JSON blob from ESI and store it.
    """
    character = models.OneToOneField(
        'waitlist.EveCharacter', # --- MODIFIED: Use string notation ---
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="pilot_snapshot"
    )
    
    # We will store the direct JSON response from ESI.
    # This is much more efficient than creating 500+ skill objects.
    # We'll need to import json to load/dump this.
    skills_json = models.TextField(blank=True, null=True, help_text="JSON response from ESI /skills/ endpoint")
    implants_json = models.TextField(blank=True, null=True, help_text="JSON response from ESI /implants/ endpoint")
    
    last_updated = models.DateTimeField(auto_now=True)

    # --- MODIFIED THIS METHOD ---
    def get_implant_ids(self):
        """Helper to get implant ID list from JSON."""
        if not self.implants_json:
            return []
        try:
            # The ESI response is just a list of type_ids, e.g., [33323, 22118]
            implant_ids = json.loads(self.implants_json)
            return implant_ids
        except json.JSONDecodeError:
            return []
    # --- END MODIFICATION ---

    def get_skills(self):
        """Helper to get skill list from JSON."""
        if not self.skills_json:
            return []
        try:
            # The ESI response is a dict, e.g.:
            # {"skills": [{"skill_id": 3339, "active_skill_level": 5}, ...], "total_sp": 150000000}
            skills_data = json.loads(self.skills_json)
            
            # We will just return the list of skill dicts for the template
            # We can add 'icon_url' here if we want, but it's slow.
            # It's better to just pass the skill_id to the template.
            return skills_data.get('skills', [])
        except json.JSONDecodeError:
            return []
            
    def get_total_sp(self):
        """Helper to get total SP from JSON."""
        if not self.skills_json:
            return 0
        try:
            skills_data = json.loads(self.skills_json)
            return skills_data.get('total_sp', 0)
        except json.JSONDecodeError:
            return 0

    def __str__(self):
        return f"Snapshot for {self.character.character_name}"