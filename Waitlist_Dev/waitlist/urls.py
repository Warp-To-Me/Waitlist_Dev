from django.urls import path
from . import views

app_name = 'waitlist'

urlpatterns = [
    # This will be the homepage
    path('', views.home, name='home'),
    
    # API endpoint for FCs to approve/deny fits
    path('api/update_fit_status/', views.api_update_fit_status, name='api_update_fit_status'),
    
    # API endpoint for live polling the waitlist HTML
    path('api/get_waitlist_html/', views.api_get_waitlist_html, name='api_get_waitlist_html'),

    # --- NEW API ENDPOINT ---
    # API endpoint for submitting a fit from the modal
    path('api/submit_fit/', views.api_submit_fit, name='api_submit_fit'),
]