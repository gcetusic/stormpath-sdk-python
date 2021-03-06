from uuid import uuid4
import datetime
import jwt
from oauthlib.common import to_unicode

from unittest import TestCase
try:
    from mock import create_autospec, MagicMock, patch
except ImportError:
    from unittest.mock import create_autospec, MagicMock, patch

from stormpath.resources.application import (
    Application, ApplicationList, StormpathCallbackResult
)
from stormpath.resources.default_relay_state import (
    DefaultRelayState, DefaultRelayStateList
)
from stormpath.resources.organization import Organization


class SamlBuildURITest(TestCase):

    def setUp(self):
        self.client = MagicMock(BASE_URL='')
        self.client.auth = MagicMock()
        self.client.auth.id = 'ID'
        self.client.auth.secret = 'SECRET'


    def test_building_saml_redirect_uri(self):
        try:
            from urlparse import urlparse
        except ImportError:
            from urllib.parse import urlparse

        app = Application(client=self.client, properties={'href': 'apphref'})

        ret = app.build_saml_idp_redirect_url(
            'http://localhost/', 'apphref/saml/sso/idpRedirect')
        try:
            jwt_response = urlparse(ret).query.split('=')[1]
        except:
            self.fail("Failed to parse ID site redirect uri")

        try:
            decoded_data = jwt.decode(
                jwt_response, verify=False, algorithms=['HS256'])
        except jwt.DecodeError:
            self.fail("Invaid JWT generated.")

        self.assertIsNotNone(decoded_data.get('iat'))
        self.assertIsNotNone(decoded_data.get('jti'))
        self.assertIsNotNone(decoded_data.get('iss'))
        self.assertIsNotNone(decoded_data.get('sub'))
        self.assertIsNotNone(decoded_data.get('cb_uri'))
        self.assertEqual(decoded_data.get('cb_uri'), 'http://localhost/')
        self.assertIsNone(decoded_data.get('path'))
        self.assertIsNone(decoded_data.get('state'))

        ret = app.build_saml_idp_redirect_url(
                'http://testserver/',
                'apphref/saml/sso/idpRedirect',
                path='/#/register',
                state='test')
        try:
            jwt_response = urlparse(ret).query.split('=')[1]
        except:
            self.fail("Failed to parse SAML redirect uri")

        try:
            decoded_data = jwt.decode(
                jwt_response, verify=False, algorithms=['HS256'])
        except jwt.DecodeError:
            self.fail("Invaid JWT generated.")

        self.assertEqual(decoded_data.get('path'), '/#/register')
        self.assertEqual(decoded_data.get('state'), 'test')


class SamlCallbackTest(SamlBuildURITest):

    def setUp(self):
        super(SamlCallbackTest, self).setUp()
        self.store = MagicMock()
        self.store.get_resource.return_value = {
            'href': 'acchref',
            'sp_http_status': 200,
            'applications': ApplicationList(
                client=self.client,
                properties={
                    'href': 'apps',
                    'items': [{'href': 'apphref'}],
                    'offset': 0,
                    'limit': 25
                })
        }
        self.store._cache_get.return_value = False # ignore nonce

        self.client.data_store = self.store

        self.app = Application(
                client=self.client,
                properties={'href': 'apphref', 'accounts': {'href': 'acchref'}})

        self.acc = MagicMock(href='acchref')
        now = datetime.datetime.utcnow()

        try:
            irt = uuid4().get_hex()
        except AttributeError:
            irt = uuid4().hex

        fake_jwt_data = {
                'exp': now + datetime.timedelta(seconds=3600),
                'aud': self.app._client.auth.id,
                'irt': irt,
                'iss': 'Stormpath',
                'sub': self.acc.href,
                'isNewSub': False,
                'state': None,
        }

        self.fake_jwt = to_unicode(jwt.encode(
            fake_jwt_data,
            self.app._client.auth.secret,
            'HS256'), 'UTF-8')

    def test_saml_callback_handler(self):
        fake_jwt_response = 'http://localhost/?jwtResponse=%s' % self.fake_jwt

        with patch.object(Application, 'has_account') as mock_has_account:
            mock_has_account.return_value = True
            ret = self.app.handle_stormpath_callback(fake_jwt_response)

        self.assertIsNotNone(ret)
        self.assertIsInstance(ret, StormpathCallbackResult)
        self.assertEqual(ret.account.href, self.acc.href)
        self.assertIsNone(ret.state)


class DefaultRelayStateTest(SamlBuildURITest):

    def setUp(self):
        super(DefaultRelayStateTest, self).setUp()
        self.store = MagicMock()
        self.client.data_store = self.store

        self.drss = DefaultRelayStateList(
            client=self.client, properties={'href': 'drss'})
        self.organization = Organization(
            client=self.client, properties={'name_key': 'NAME KEY'})

    def test_default_relay_state_create_empty(self):
        self.drss.create()

        self.store.create_resource.assert_called_once_with(
            'drss', {}, params={})

    def test_default_relay_state_create_organization(self):
        self.drss.create({'organization': self.organization})

        self.store.create_resource.assert_called_once_with(
            'drss', {'organization': {'nameKey': 'NAME KEY'}}, params={})

    def test_default_relay_state_create_organization_name_key(self):
        self.drss.create({'organization': {'name_key': 'ANOTHER NAME KEY'}})

        self.store.create_resource.assert_called_once_with(
            'drss',
            {'organization': {'nameKey': 'ANOTHER NAME KEY'}},
            params={})
