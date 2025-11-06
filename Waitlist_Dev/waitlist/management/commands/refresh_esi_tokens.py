import requests
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from esi.models import Token
from waitlist.models import EveCharacter

class Command(BaseCommand):
    help = 'Refreshes ESI tokens that have not been used in 7 days.'

    def handle(self, *args, **options):
        # 1. Define the cutoff date
        # --- FIX: We query our EveCharacter model, not the Token model ---
        cutoff_date = timezone.now() - timedelta(days=7)
        
        # 2. Find all EveCharacters with stale tokens
        stale_characters = EveCharacter.objects.filter(token_expiry__lt=cutoff_date)
        # --- END FIX ---
        
        total_tokens = stale_characters.count()
        refreshed_count = 0
        failed_count = 0

        self.stdout.write(f"Found {total_tokens} stale tokens to refresh.")

        # 3. Loop through and refresh them
        for eve_char in stale_characters:
            try:
                # --- FIX: Get the associated Token object to refresh it ---
                token = Token.objects.filter(character_id=eve_char.character_id).first()
                
                if not token:
                    self.stdout.write(self.style.ERROR(f"No Token found for {eve_char.character_name}. Deleting character."))
                    eve_char.delete()
                    failed_count += 1
                    continue
                # --- END FIX ---

                self.stdout.write(f"Refreshing token for {eve_char.character_name} ({eve_char.character_id})...")
                
                # This makes the ESI call to get a new access token
                token.refresh() 
                
                # 4. Sync our local EveCharacter model
                # token.expires is an in-memory attribute added by .refresh()
                eve_char.access_token = token.access_token
                eve_char.token_expiry = token.expires 
                eve_char.save()
                    
                self.stdout.write(self.style.SUCCESS(f"Successfully refreshed token for {eve_char.character_name}."))
                refreshed_count += 1

            except requests.exceptions.HTTPError as e:
                # 5. Handle failed refresh (e.g., 400 Bad Request if revoked)
                if e.response.status_code == 400:
                    self.stdout.write(self.style.ERROR(f"Refresh failed for {eve_char.character_name}. Token is invalid. Deleting."))
                    # Delete the invalid token and its associated character
                    if token:
                        token.delete()
                    eve_char.delete()
                    failed_count += 1
                else:
                    # Other ESI error
                    self.stdout.write(self.style.ERROR(f"ESI error for {eve_char.character_name}: {e}"))
                    failed_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"An unexpected error occurred for {eve_char.character_name}: {e}"))
                failed_count += 1

        self.stdout.write(self.style.SUCCESS(f"\nRefresh complete. Refreshed: {refreshed_count}, Failed/Deleted: {failed_count}"))