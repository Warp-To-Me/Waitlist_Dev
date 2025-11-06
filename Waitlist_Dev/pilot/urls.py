from django.urls import path
from . import views

app_name = 'pilot'

urlpatterns = [
    # This URL will be /pilot/<character_id>/
    path('<int:character_id>/', views.pilot_detail, name='pilot_detail'),
]