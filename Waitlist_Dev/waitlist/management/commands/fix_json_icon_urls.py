from django.core.management.base import BaseCommand
from waitlist.models import DoctrineFit, ShipFit
import json

# ---
# --- NEW: Import logging
# ---
import logging
# Get a logger for this specific Python file
logger = logging.getLogger(__name__)
# ---
# --- END NEW LOGGING IMPORT
# ---

class Command(BaseCommand):
    help = 'Finds and fixes broken "https." icon URLs in parsed_fit_json fields.'

    def handle(self, *args, **options):
        # --- NEW: Use logger instead of stdout ---
        # Configure logger
        logger.parent.handlers[0].setFormatter(
            logging.Formatter('{levelname} {asctime} {module} {message}', style='{')
        )
        logger.parent.setLevel(logging.INFO) # Set to INFO for this command
        
        logger.info("--- Starting to fix broken icon URLs ---")
        
        # --- Fix Doctrine Fits ---
        logger.info("Scanning DoctrineFits...")
        doctrine_fits_to_update = []
        for fit in DoctrineFit.objects.filter(parsed_fit_json__isnull=False):
            if '"icon_url": "https.' in fit.parsed_fit_json:
                logger.warning(f"  Found broken URL in: {fit.name}")
                fit.parsed_fit_json = fit.parsed_fit_json.replace(
                    '"icon_url": "https.', 
                    '"icon_url": "https://'
                )
                doctrine_fits_to_update.append(fit)
        
        if doctrine_fits_to_update:
            DoctrineFit.objects.bulk_update(doctrine_fits_to_update, ['parsed_fit_json'], batch_size=100)
            logger.info(f"Fixed {len(doctrine_fits_to_update)} DoctrineFits.")
        else:
            logger.info("No broken DoctrineFits found.")

        # --- Fix Submitted ShipFits ---
        logger.info("\nScanning ShipFits...")
        ship_fits_to_update = []
        for fit in ShipFit.objects.filter(parsed_fit_json__isnull=False):
            if '"icon_url": "https." in fit.parsed_fit_json:
                # No need to log every single one, just fix them
                fit.parsed_fit_json = fit.parsed_fit_json.replace(
                    '"icon_url": "https.', 
                    '"icon_url": "https://'
                )
                ship_fits_to_update.append(fit)
        
        if ship_fits_to_update:
            ShipFit.objects.bulk_update(ship_fits_to_update, ['parsed_fit_json'], batch_size=100)
            logger.info(f"Fixed {len(ship_fits_to_update)} ShipFits.")
        else:
            logger.info("No broken ShipFits found.")

        logger.info("\n--- Icon URL fix complete ---")
        # --- END NEW ---