from django.urls import path
from . import views

app_name = 'pilot'

urlpatterns = [
    # This URL will be /pilot/<character_id>/
    path('<int:character_id>/', views.pilot_detail, name='pilot_detail'),
    
    # This is the background URL our JavaScript will call
    path('api/refresh/<int:character_id>/', views.api_refresh_pilot, name='api_refresh_pilot'),
    
    # API URL for setting main character
    path('api/set_main/', views.api_set_main_character, name='api_set_main_character'),
    
    # API URL for X-Up modal implant list
    path('api/get_implants/', views.api_get_implants, name='api_get_implants'),
]