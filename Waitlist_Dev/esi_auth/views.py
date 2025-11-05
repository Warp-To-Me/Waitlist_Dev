from django.shortcuts import redirect
from django.contrib.auth import logout
from django.conf import settings

def esi_logout(request):
    """
    Logs the user out of the Django application.
    
    Note: This does NOT log the user out of the EVE SSO website.
    For a full "log out everywhere", you would also need to redirect
    the user to the EVE SSO logout page. For this app, logging
    out of Django is usually sufficient.
    """
    logout(request)
    
    # Redirect back to the homepage
    # We use 'home' which we named in the main eve_waitlist/urls.py
    return redirect('home')

#
# The 'esi_login' and 'esi_callback' views have been removed.
# The 'django-esi' library now provides these views for us
# via the 'include('esi.urls')' in our main urls.py.
#

