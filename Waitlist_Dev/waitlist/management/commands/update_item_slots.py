# --- NEW FILE ---
import time
from django.core.management.base import BaseCommand
from django.db import transaction

from pilot.models import EveType
from esi.clients import EsiClientProvider

# ---
# --- IMPORTANT: These helpers are copied from fit_parser.py
# --- to make this script self-contained and avoid import issues.
# ---
def _get_dogma_value(dogma_attributes, attribute_id):
    """Safely find a dogma attribute value from the list."""
    if not dogma_attributes:
        return None
    for attr in dogma_attributes:
        if attr['attribute_id'] == attribute_id:
            return attr.get('value')
    return None
# ---
# --- END HELPERS
# ---

class Command(BaseCommand):
    help = 'Scans the EveType table for items missing slot data and backfills them from ESI.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("--- Starting EveType Slot Backfill ---"))
        
        # Find all types that are missing *both* ship slot data and module slot data.
        # This prevents us from re-processing items we've already checked.
        types_to_update = EveType.objects.filter(
            hi_slots__isnull=True, 
            slot_type__isnull=True
        ).select_related('group')
        
        total_types = types_to_update.count()
        if total_types == 0:
            self.stdout.write(self.style.SUCCESS("All EveTypes are already up-to-date. No backfill needed."))
            return

        self.stdout.write(self.style.WARNING(f"Found {total_types} types missing slot data. Fetching from ESI..."))
        self.stdout.write("This may take a while.")

        esi = EsiClientProvider()
        updated_count = 0
        failed_count = 0
        
        # Process in batches to be nice to the database
        for eve_type in types_to_update:
            try:
                type_data = esi.client.Universe.get_universe_types_type_id(
                    type_id=eve_type.type_id
                ).results()
                
                dogma_attrs = type_data.get('dogma_attributes', [])
                group = eve_type.group # We already have this from select_related
                
                # 1. Get ship slot counts (if applicable)
                eve_type.hi_slots = _get_dogma_value(dogma_attrs, 14)
                eve_type.med_slots = _get_dogma_value(dogma_attrs, 13)
                eve_type.low_slots = _get_dogma_value(dogma_attrs, 12)
                eve_type.rig_slots = _get_dogma_value(dogma_attrs, 1137)
                eve_type.subsystem_slots = _get_dogma_value(dogma_attrs, 1367)

                # 2. Get module slot type (if applicable)
                slot_type = None
                if group.category_id == 18: # Category 18 is Drone
                    slot_type = 'drone'
                elif _get_dogma_value(dogma_attrs, 125) == 1: # hiSlot
                    slot_type = 'high'
                elif _get_dogma_value(dogma_attrs, 126) == 1: # medSlot
                    slot_type = 'mid'
                elif _get_dogma_value(dogma_attrs, 127) == 1: # lowSlot
                    slot_type = 'low'
                elif _get_dogma_value(dogma_attrs, 1154) == 1: # rigSlot
                    slot_type = 'rig'
                elif _get_dogma_value(dogma_attrs, 1373) == 1: # subSystem
                    slot_type = 'subsystem'
                
                eve_type.slot_type = slot_type
                
                # 3. Save the updated type
                eve_type.save()
                
                updated_count += 1
                self.stdout.write(self.style.SUCCESS(f"  Updated: {eve_type.name}"))
                
                # Be nice to ESI
                time.sleep(0.05) 

            except Exception as e:
                failed_count += 1
                self.stdout.write(self.style.ERROR(f"  Failed: {eve_type.name} (ID: {eve_type.type_id}). Error: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\n--- Backfill Complete ---"))
        self.stdout.write(self.style.SUCCESS(f"Successfully updated: {updated_count}"))
        self.stdout.write(self.style.ERROR(f"Failed to update:   {failed_count}"))