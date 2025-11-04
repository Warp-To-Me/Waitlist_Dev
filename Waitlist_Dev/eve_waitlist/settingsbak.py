"""
Django settings for eve_waitlist project.
"""

import os
from pathlib import Path
import pymysql

# Tell Django to use PyMySQL
pymysql.install_as_MySQLdb()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# REQUIRED BY ESI: Add your contact email here.
# This is so CCP can contact you if your app misbehaves.
ESI_USER_CONTACT_EMAIL = 'tekeve@gmail.com' 
#
# Set your callback URL in the EVE dev portal to:
# http://127.0.0.1:8000/auth/callback/  (for local testing)
# https://your-domain.com/auth/callback/ (for production)
#
ESI_SSO_CLIENT_ID = '6333f47f40c5401f96ad0f16799c2301'
ESI_SSO_CLIENT_SECRET = 'eat_2dOLfdF6zBQoviRtq9bixEAQkVhHJm9dz_mMuZN'
ESI_SSO_CALLBACK_URL = 'http://127.0.0.1:8000/auth/callback/'

# This is the login URL for the `esi_auth` app
LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/'  # Redirect to homepage after login
LOGOUT_REDIRECT_URL = '/'
# --- End ESI Configuration ---


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.0/howto/deployment/checklist/

# !! IMPORTANT !!
# Change this to a unique, random string in production!
SECRET_KEY = 'Y9jzcvWCtyCgVp1AlnBJMvb0kH4bPuTf'

# !! IMPORTANT !!
# Set DEBUG = False in production
DEBUG = True

# Add your production domain here
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']


# Application definition

INSTALLED_APPS = [
    # Django Core Apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-Party Apps
    'esi',  # django-esi for ESI auth and API calls

    # Your Project's Apps
    'esi_auth.apps.EsiAuthConfig',
    'waitlist.apps.WaitlistConfig',
    'fleet_admin.apps.FleetAdminConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'eve_waitlist.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # A central folder for HTML templates
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'eve_waitlist.wsgi.application'


# --- Database Configuration ---
# https://docs.djangoproject.com/en/4.0/ref/settings/#databases
#
# This is pre-configured for MySQL, as you requested.
# 1. Create a database in HeidiSQL (e.g., "eve_waitlist")
# 2. Update the 'NAME', 'USER', and 'PASSWORD' fields below.

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'waitlist-dev',     # The database name you created
        'USER': 'root',             # Your MySQL username
        'PASSWORD': 'root',  # Your MySQL password
        'HOST': '127.0.0.1',        # Or 'localhost'
        'PORT': '3306',
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}
# --- End Database Configuration ---


# Password validation
# https://docs.djangoproject.com/en/4.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# We are using Django's built-in User model, but we link it
# to our `EveCharacter` model in `waitlist/models.py`
AUTH_USER_MODEL = 'auth.User'


# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.0/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Default primary key field type
# https://docs.djangoproject.com/en/4.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Tell Django what the login URL is.
# This is the fix for the NoReverseMatch error.
LOGIN_URL = 'esi:login'
