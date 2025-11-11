"""
URL configuration for eve_waitlist project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Point the root URL to our waitlist app
    path('', include('waitlist.urls')),
    
    path('admin/', admin.site.urls),
    
    # Our custom auth views (login, logout, and callback)
    path('auth/', include('esi_auth.urls', namespace='esi_auth')),
    
    # URLs for the pilot app
    path('pilot/', include('pilot.urls', namespace='pilot')),

    # Add the django_eventstream URLs
    # This is what our server-sent events (SSE) connect to
    path('events/', include('django_eventstream.urls')),
]