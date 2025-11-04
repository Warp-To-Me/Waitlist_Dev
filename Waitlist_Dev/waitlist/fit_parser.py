import eveparse
from .models import ShipFit, FitCheckRule

def parse_and_validate_fit(ship_fit: ShipFit):
    """
    Parses a ship fit and validates it against the rules
    for its waitlist.
    
    This is where you'll write your core logic.
    """
    
    raw_text = ship_fit.raw_fit
    waitlist = ship_fit.waitlist
    character = ship_fit.character
    
    try:
        # 1. Parse the fit using eveparse
        # eveparse returns a list of (item_name, quantity) tuples
        parsed_items = eveparse.parse_multi_line(raw_text)
        
        # You'll likely get a list of tuples, e.g.:
        # [('Vargur', 1), ('Large Shield Booster II', 1), ('100MN Y-S8 Compact Afterburner', 1)]
        # You'll need to process this into a more usable format, like a dict
        
        fit_modules = {name: quantity for name, quantity in parsed_items}
        
    except eveparse.ParserError as e:
        ship_fit.status = 'DENIED'
        ship_fit.review_notes = f"Could not parse fit. Error: {e}"
        ship_fit.save()
        return False, ship_fit.review_notes
        
    # 2. Get the rules for this waitlist
    rules = waitlist.rules.filter(is_active=True)
    
    validation_errors = []
    
    for rule in rules:
        if rule.rule_type == 'MUST_HAVE':
            if rule.item_name not in fit_modules:
                validation_errors.append(f"Missing required module: {rule.item_name}")
            elif fit_modules[rule.item_name] < rule.value:
                validation_errors.append(f"Not enough {rule.item_name}. Need {rule.value}, have {fit_modules[rule.item_name]}.")
        
        elif rule.rule_type == 'MUST_NOT_HAVE':
            if rule.item_name in fit_modules:
                validation_errors.append(f"Fit contains forbidden module: {rule.item_name}")
                
        elif rule.rule_type == 'MIN_SKILL':
            # This is more complex. You would:
            # 1. Use django-esi to get the user's token:
            #    token = esi.get_token_for_user(character.user, scopes=['esi-skills.read_skills.v1'])
            # 2. Make an ESI call:
            #    skills_data = esi.client.Skills.get_characters_character_id_skills(
            #        character_id=character.character_id,
            #        token=token.access_token
            #    ).results()
            # 3. Get the TypeID for the skill name (this requires SDE data)
            # 4. Check the skill level from skills_data
            #
            # For now, we'll just placeholder it.
            pass
            
    # 3. Update the fit status
    if validation_errors:
        ship_fit.status = 'DENIED'
        ship_fit.review_notes = "\n".join(validation_errors)
        ship_fit.save()
        return False, ship_fit.review_notes
    else:
        # If no errors, mark as pending for FC review
        # Or, if you are confident, auto-approve
        ship_fit.status = 'PENDING' 
        ship_fit.review_notes = "Fit passed automatic checks. Awaiting FC review."
        ship_fit.save()
        return True, "Fit passed automatic checks."
