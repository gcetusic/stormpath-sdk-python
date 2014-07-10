"""Stormpath Application resource mappings."""

from datetime import datetime
import json
from uuid import uuid4
import urllib

from .base import (
    CollectionResource,
    DeleteMixin,
    DictMixin,
    Resource,
    SaveMixin,
    StatusMixin,
)
from .login_attempt import LoginAttemptList
from ..id_site import IdSiteCallbackResult
from ..nonce import Nonce
from .password_reset_token import PasswordResetTokenList


class Application(Resource, DeleteMixin, DictMixin, SaveMixin, StatusMixin):
    """Stormpath Application resource.

    More info in documentation:
    http://docs.stormpath.com/python/product-guide/#applications
    """
    writable_attrs = (
        'description',
        'name',
        'status',
    )

    @staticmethod
    def get_resource_attributes():
        from .account import AccountList
        from .account_store_mapping import (
            AccountStoreMapping,
            AccountStoreMappingList,
        )
        from .group import GroupList
        from .tenant import Tenant
        from .api_key import ApiKeyList

        return {
            'accounts': AccountList,
            'api_keys': ApiKeyList,
            'account_store_mappings': AccountStoreMappingList,
            'default_account_store_mapping': AccountStoreMapping,
            'default_group_store_mapping': AccountStoreMapping,
            'groups': GroupList,
            'login_attempts': LoginAttemptList,
            'password_reset_tokens': PasswordResetTokenList,
            'tenant': Tenant,
        }

    def authenticate_account(self, login, password, expand=None,
            account_store=None):
        """Authenticate Account inside the Application.

        :param login: Username or email address

        :param password: Unencrypted user password

        :param expand:
            A :class:`stormpath.resources.base.Expansion` object (optional)

        :param account_store:
            A specific :class:`stormpath.resources.account_store.AccountStore`
            object to authenticate against (optional)
        """
        return self.login_attempts.basic_auth(login, password, expand,
            account_store)

    def get_provider_account(self, provider, **provider_kwargs):
        """Used for getting account data from 3rd party Providers
        (ie. Google, Facebook)

        :param provider: Can be one of the following Constants:

            * :const:`stormpath.resources.provider.Provider.GOOGLE`

            * :const:`stormpath.resources.provider.Provider.FACEBOOK`

            * :const:`stormpath.resources.provider.Provider.STORMPATH`


        :param provider_kwargs: Which specific kwargs are needed depends on the chosen Provider.

            {
                'code': '...',

                'access_token': '...',

                'client_id': '...',

                'client_secret': '...'
            }



        """
        provider_data = provider_kwargs.copy()
        provider_data['provider_id'] = provider

        return self.accounts.create({
            'provider_data': provider_data
        })

    def send_password_reset_email(self, email):
        """Send a password reset email.

        More info in documentation:
        http://docs.stormpath.com/rest/product-guide/#reset-an-accounts-password

        :param email: Email address to send the email to.
        """
        token = self.password_reset_tokens.create({'email': email})
        return token.account

    def verify_password_reset_token(self, token):
        """Verify password reset by using a token.

        :param token: password reset token extracted from the URL.
        """
        return self.password_reset_tokens[token].account

    def reset_account_password(self, token, password):
        """Resets the password for an account.

        :param token: password reset token.
        :param password: new password
        """
        if token.account.email not in [a.email for a in self.accounts]:
            raise ValueError('Unrecognized account for this application %s' %
                repr(token.account))
        href = self.password_reset_tokens.build_reset_href(token)
        data = {'password': password}
        self._store.create_resource(href=href, data=data)

    def authenticate(self, allowed_scopes, http_method, uri, body, headers, **kwargs):
        from ..api_auth import authenticate as api_authenticate

        return api_authenticate(self, allowed_scopes, http_method, uri, body, headers, **kwargs)

    def build_id_site_redirect_url(self, api_key, callback_uri, path=None, state=None):
        """Builds a redirect uri for ID site.

        :param api_key: :class:`stormpath.resources.api_key.ApiKey` object used for interacting
            with the Stormpath API.

        :param callback_uri: Callback URI to witch Stormpaath will redirect after
            the user has entered their credentials on the ID site. Note: For security reasons
            this is required to be the same as "Authorized Redirect URI" in the
            Admin Console's ID Site settings.

        :param path:
            An optional string indicating to wich template we should redirect the user to.
            By default it will redirect to the login screen but you can redirect to the
            registration or forgot password screen with '/#/register' and '/#/forgot' respectively.

        :param state: an optional string that stores information that your application needs
            after the user is redirected back to your application

        :return: A URI to witch to redirect the user.
        """
        import jwt
        from oauthlib.common import to_unicode
        SSO_ENDPOINT = "https://api.stormpath.com/sso";

        body = {
            'iat': datetime.utcnow(),
            'jti': uuid4().get_hex(),
            'iss': api_key.id,
            'sub': self.href,
            'cb_uri': callback_uri,
        }
        if path:
            body['path'] = path
        if state:
            body['state'] = state

        jwt_signature = to_unicode(jwt.encode(body, api_key.secret, 'HS256'), 'UTF-8')
        url_params = {'jwtRequest': jwt_signature}
        return SSO_ENDPOINT + '?' + urllib.urlencode(url_params)

    def handle_id_site_callback(self, url_response):
        """Handles the callback from the ID site.

        :param url_response: A string representing the full url (with it's params) to witch the
            ID redirected to.

        :return: A :class:`stormpath.id_site.IdSiteCallbackResult` object. Which holds the
            :class:`stormpath.resources.account.Account` object and the state (if any was passed
            along when creating the redirect uri).

       """
        try:
            from urlparse import urlparse
        except ImportError:
            from urllib.parse import urlparse

        import jwt
        try:
            jwt_response = urlparse(url_response).query.split('=')[1]
        except:
            return None

        try:
            decoded_data = jwt.decode(jwt_response, verify=False)
        except jwt.DecodeError:
            return None

        api_key_id = decoded_data.get('aud')
        if not api_key_id:
            return None
        api_key = self.api_keys.get_key(client_id=api_key_id)
        if not api_key:
            return None

        # validate signature
        try:
            decoded_data = jwt.decode(jwt_response, api_key.secret)
        except (jwt.DecodeError, jwt.ExpiredSignature):
            return None


        nonce = Nonce(decoded_data['irt'])

        # check if nonce is in cache already
        # if it is throw an Exception
        if self._store._cache_get(nonce.href):
            raise ValueError('JWT has already been used.')

        # store nonce in cache store
        self._store._cache_put(href=nonce.href, data={'value': nonce.value})

        issuer = decoded_data['iss']
        account_href = decoded_data['sub']
        is_new_account = decoded_data['isNewSub']
        state = decoded_data['state']

        account = self.accounts.get(account_href)
        # We modify the internal parameter sp_http_status which indicates if an account
        # is new (ie. just created). This is so we can take advantage of the account.is_new_account
        # property
        account.sp_http_status  # NOTE: this forces account retrieval and building of the actual Account object
        account.__dict__['sp_http_status'] = 201 if is_new_account else 200
        return IdSiteCallbackResult(account=account, state=state)


class ApplicationList(CollectionResource):
    """Application resource list."""
    create_path = '/applications'
    resource_class = Application
