# EVE Online Waitlist Utility
This is a starter project for your EVE Online waitlist utility, built with Python and Django.
It's designed to be modular, and provides the foundation for all the features an Incursion community might want.

## Project Structure
### This project is organized into a main project folder (eve_waitlist) and several modular "apps":

/eve_waitlist/: This is the main Django project folder.

settings.py: This is your most important configuration file. I have set it up to use MySQL and included placeholders for your ESI app credentials.
urls.py: The main URL router for the entire project.


/esi_auth/: A Django app to handle all ESI (OAuth) authentication.

views.py: Contains the logic to redirect users to the EVE SSO login page and handle the callback to authenticate them and create their user accounts.


/waitlist/: A Django app for the core waitlist functionality.

models.py: Defines your database tables (models) for things like Waitlist, ShipFit, and EveCharacter.
fit_parser.py: A stub file where you'll build your fit parsing and validation logic.


/fleet_admin/: A Django app to configure the admin backend.
admin.py: This file tells the Django admin site how to display your models. This is where you'll empower your Fleet Commanders (FCs) to approve/deny fits.
manage.py: The main script you'll use to run your web server and manage the project.


requirements.txt: A list of the Python packages you'll need.

## How to Get Started
### Create your ESI Application:
Go to the EVE Online Developers Portal.
Create a new application.
Set the "Callback URL" to http://127.0.0.1:8000/auth/callback/ for local development.
You will need to request the necessary ESI scopes for skills, implants, fleet invites, etc. 
A good starting list might be:
esi-skills.read_skills.v1
esi-clones.read_implants.v1
esi-fleets.write_fleet.v1
publicData
Once created, you'll get a Client ID and a Secret Key.

### Set up your Environment (in VS 2022):
Open this project folder in Visual Studio 2022.
Create a Python virtual environment: python -m venv venv
Activate it: .\venv\Scripts\activate
Install the required packages: pip install -r requirements.txt
Configure settings.py:Open eve_waitlist/settings.py.
Database: Fill in the DATABASES section with your MySQL credentials (the database name, user, and password you use in HeidiSQL). 
You'll need to create the database in HeidiSQL first.

ESI: Fill in the ESI_SSO_CLIENT_ID and ESI_SSO_CLIENT_SECRET with the values from Step 1.

### Initialize Your Database:
Run the initial database "migrations" to create all the Django admin and app tables in your MySQL database:
python manage.py migrate

### Create a Superuser (Admin):
This creates the first "Admin" account for you to manage other users and permissions.
python manage.py createsuperuser
Follow the prompts to create a username and password.

### Run the Development Server:
Start the website!
python manage.py runserver
You can now access your site at http://127.0.0.1:8000/.Visit http://127.0.0.1:8000/admin/ to log in to the admin backend with the superuser you just created.
Visit http://127.0.0.1:8000/auth/login/ to test the ESI login flow!

### Next Steps
From here, you have the foundation to build all your features:
Fit Parsing: Open waitlist/fit_parser.py. 
This is where you'll use the eveparse library to parse the raw fit text from the ShipFit model and check it against rules.
Admin Views: Open fleet_admin/admin.py. 
You can heavily customize this to add "Admin Actions" (e.g., a button to "Approve Fit"), filters, and display more character information.
Frontend (UI): You'll need to create the HTML templates for users to see the waitlist, paste their fits, and view their character info. 
You can do this with Django's built-in template system or by building a separate frontend (e.g., in React) that talks to a Django REST Framework API.
ESI Calls: Use the django-esi library to make ESI calls. After a user logs in, you can get their token and fetch their skills, implants, etc., and store that information.
Good luck, capsuleer! This is a solid start.