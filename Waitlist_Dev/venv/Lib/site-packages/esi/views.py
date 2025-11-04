import logging

from requests_oauthlib import OAuth2Session

from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse
from django.http.response import HttpResponseBadRequest

from esi.models import CallbackRedirect, Token
from esi import app_settings
from .decorators import tokens_required

logger = logging.getLogger(__name__)


def sso_redirect(request, scopes=None, return_to=None):
    """
    Generates a :model:`esi.CallbackRedirect` for the specified request.
    Redirects to EVE for login.
    Accepts a view or URL name as a redirect after SSO.
    """
    logger.debug(
        "Initiating redirect of %s session %s",
        request.user,
        request.session.session_key[:5] if request.session.session_key else '[no key]'
    )
    if scopes is None:
        scopes = list()
    elif isinstance(scopes, str):
        scopes = list([scopes])

    # ensure only one callback redirect model per session
    if request.session.session_key:
        CallbackRedirect.objects\
            .filter(session_key=request.session.session_key).delete()

    # ensure we have a session
    if not request.session.exists(request.session.session_key):
        logger.debug("Creating new session before redirect.")
        request.session.create()

    if return_to:
        url = reverse(return_to)
    else:
        url = request.get_full_path()

    oauth = OAuth2Session(
        app_settings.ESI_SSO_CLIENT_ID,
        redirect_uri=app_settings.ESI_SSO_CALLBACK_URL,
        scope=scopes
    )
    redirect_url, state = oauth.authorization_url(app_settings.ESI_OAUTH_LOGIN_URL)

    CallbackRedirect.objects.create(
        session_key=request.session.session_key, state=state, url=url
    )
    logger.debug(
        "Redirecting %s session %s to SSO. Callback will be redirected to %s",
        request.user,
        request.session.session_key[:5],
        url
    )
    return redirect(redirect_url)


def receive_callback(request):
    """
    Parses SSO callback, validates, retrieves :model:`esi.Token`,
    and internally redirects to the target url.
    """
    logger.debug(
        "Received callback for %s session %s",
        request.user,
        request.session.session_key[:5]
    )
    # make sure request has required parameters
    code = request.GET.get('code', None)
    state = request.GET.get('state', None)
    if not code or not state:
        logger.warning("Missing parameters for code exchange.")
        return HttpResponseBadRequest()

    callback = get_object_or_404(
        CallbackRedirect, state=state, session_key=request.session.session_key
    )
    token = Token.objects.create_from_request(request)
    callback.token = token
    callback.save()
    logger.debug(
        "Processed callback for %s session %s. Redirecting to %s",
        request.user,
        request.session.session_key[:5],
        callback.url
    )
    return redirect(callback.url)


def select_token(request, scopes='', new=False):
    """
    Presents the user with a selection of applicable tokens for the requested view.
    """

    @tokens_required(scopes=scopes, new=new)
    def _token_list(r, tokens):
        # Single Scope as string will break the Parser in the template
        if isinstance(scopes, str):
            scopes_output = [scopes]
        else:
            scopes_output = scopes

        # fake distint on character_name to not show duplicates
        # MySQL doesn't support distint on field.
        token_output = []
        _characters = set()
        for t in tokens:
            if t.character_name in _characters:
                continue
            token_output.append(t)
            _characters.add(t.character_name)

        context = {
            'tokens': token_output,
            'scopes': scopes_output
        }

        return render(r, 'esi/select_token.html', context=context)

    return _token_list(request)
