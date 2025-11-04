from django.urls import path
from . import views

# THE FIX IS HERE:
# We're adding this line to tell Django what the app_name is.
# This is required when using a namespace in the main urls.py
app_name = 'esi_auth'

# These URL patterns are prefixed with '/auth/' (from the main urls.py)

urlpatterns = [
    # Full path will be /auth/logout/
    path('logout/', views.esi_logout, name='logout'),
]

