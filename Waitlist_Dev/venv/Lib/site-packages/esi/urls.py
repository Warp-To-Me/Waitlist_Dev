from django.urls import path

from . import views


app_name = 'esi'

urlpatterns = [
    path('callback/', views.receive_callback, name='callback'),
]
