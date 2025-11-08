import json
from django.core.management.base import BaseCommand
from django.db import transaction

from waitlist.models import DoctrineFit, ShipFit, FitSubstitutionGroup
from pilot.models import PilotSnapshot, EveType
# Import our new helper function
from waitlist.fit_parser import get_or_cache_eve_type_by_id

class Command(BaseCommand):
    help = 'Scans the database for all referenced EveType IDs and back-fills the cache from ESI.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("--- Starting SDE Cache Backfill ---"))
        
        all_ids = set()

        # 1. Get IDs from DoctrineFit (ship_type and items_json)
        self.stdout.write("Scanning Doctrine Fits...")
        for fit in DoctrineFit.objects.all():
            if fit.ship_type_id:
                all_ids.add(fit.ship_type_id)
            try:
                if fit.fit_items_json:
                    item_ids = json.loads(fit.fit_items_json).keys()
                    all_ids.update(int(i) for i in item_ids)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  Could not parse JSON for DoctrineFit {fit.id}: {e}"))

        # 2. Get IDs from FitSubstitutionGroup
        self.stdout.write("Scanning Substitution Groups...")
        for group in FitSubstitutionGroup.objects.all():
            if group.base_item_id:
                all_ids.add(group.base_item_id)
            all_ids.update(group.substitutes.values_list('type_id', flat=True))

        # 3. Get IDs from ShipFit (ship_type_id and parsed_fit_json)
        self.stdout.write("Scanning Submitted ShipFits...")
        for fit in ShipFit.objects.all():
            if fit.ship_type_id:
                all_ids.add(fit.ship_type_id)
            try:
                if fit.parsed_fit_json:
                    items = json.loads(fit.parsed_fit_json)
                    for item in items:
                        if item.get('type_id'):
                            all_ids.add(item['type_id'])
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  Could not parse JSON for ShipFit {fit.id}: {e}"))

        # 4. Get IDs from PilotSnapshot (skills_json and implants_json)
        self.stdout.write("Scanning Pilot Snapshots...")
        for snapshot in PilotSnapshot.objects.all():
            try:
                if snapshot.skills_json:
                    skills_data = json.loads(snapshot.skills_json)
                    skill_ids = [s['skill_id'] for s in skills_data.get('skills', [])]
                    all_ids.update(skill_ids)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  Could not parse skills JSON for {snapshot.character_id}: {e}"))
            
            try:
                if snapshot.implants_json:
                    implant_ids = json.loads(snapshot.implants_json)
                    all_ids.update(implant_ids)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  Could not parse implants JSON for {snapshot.character_id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\nFound {len(all_ids)} unique type IDs referenced in the database."))

        # 5. Find which IDs are missing from the EveType table
        existing_ids = set(EveType.objects.values_list('type_id', flat=True))
        missing_ids = all_ids - existing_ids
        
        # Remove None if it's in the set
        missing_ids.discard(None)

        if not missing_ids:
            self.stdout.write(self.style.SUCCESS("All referenced types are already cached. Database is up-to-date."))
            return

        self.stdout.write(self.style.WARNING(f"Fetching {len(missing_ids)} missing types from ESI..."))

        # 6. Fetch all missing IDs in a single transaction
        fetched_count = 0
        failed_count = 0
        try:
            with transaction.atomic():
                for i, type_id in enumerate(missing_ids):
                    self.stdout.write(f"  Fetching ID {type_id} ({i+1} of {len(missing_ids)})...")
                    eve_type = get_or_cache_eve_type_by_id(type_id)
                    if eve_type:
                        self.stdout.write(self.style.SUCCESS(f"    -> Cached: {eve_type.name} (Group: {eve_type.group.name})"))
                        fetched_count += 1
                    else:
                        self.stdout.write(self.style.ERROR(f"    -> FAILED to fetch type ID {type_id}"))
                        failed_count += 1
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred during the transaction: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\n--- Backfill Complete ---"))
        self.stdout.write(self.style.SUCCESS(f"Successfully fetched: {fetched_count}"))
        self.stdout.write(self.style.ERROR(f"Failed to fetch:     {failed_count}"))