from django.urls import path
from . import views

# This is required when using a namespace in the main urls.py
app_name = 'esi_auth'

# These URL patterns are prefixed with '/auth/' (from the main urls.py)

urlpatterns = [
    # Full path will be /auth/login/
    path('login/', views.esi_login, name='login'),
    
    # Full path will be /auth/logout/
    path('logout/', views.esi_logout, name='logout'),
    
    # Full path will be /auth/callback/
    # We are explicitly routing the callback to the real view
    # from the 'esi' library.
    path('callback/', views.esi_callback, name='callback'),
    
    # Full path will be /auth/sso_complete/
    # This is our view that performs the actual
    # Django login after the callback is done.
    path('sso_complete/', views.sso_complete_login, name='sso_complete'),
]