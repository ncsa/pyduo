import grab
import json
import logging
import pathlib
import pprint
import re
import time

LOGR = logging.getLogger(__name__)


class PyDuo( object ):

    # URL = {
    #     'vsl': 'https://my.engr.illinois.edu/vacation/',
    #     'setdate': 'https://my.engr.illinois.edu/vacation/setdate.asp',
    #     'myemployees': 'https://my.engr.illinois.edu/vacation/myemployees.asp',
    #     'userdetails': 'https://my.engr.illinois.edu/vacation/userdetails.asp',
    #     'approve': 'https://my.engr.illinois.edu/vacation/change_status.asp?ns=A',
    # }
    FN_COOKIES = pathlib.Path( 'cookiefile' )


    def __init__( self, username, password, *a, **k ):
        self.usr = username
        self.pwd = password
        self.userpwd = '{}:{}'.format( username, password )
        self.g = grab.Grab()
        self.g.setup( cookiefile=self.FN_COOKIES )
        self.FN_COOKIES.touch()
        if LOGR.getEffectiveLevel() is logging.DEBUG:
            self.g.setup( debug=True, log_dir='LOGS' )


    def _go( self, url, **kwargs ):
        LOGR.debug( f'URL: {url}' )
        self.g.go( url, **kwargs )
        # if we got redirected to the login page, then have to login
        url_parts = self.g.doc.url_details()
        # url_details is a SplitResult object ...
        # SplitResult(scheme='https', netloc='shibboleth.illinois.edu', path='/login.asp', query='/vacation/index.asp%7C', fragment='')
        if url_parts.path.startswith( '/login' ):
            LOGR.info( 'Found login page' )
            self._do_login()


    def _do_login( self ):

        LOGR.info( 'Attempting to login ...' )
        # Assume the login form is already loaded
        # (from the request that just happened in self._go)
        self.g.submit()

        # login goes to shibboleth,
        # .. which generates SAMLRequest and redirects to
        # .. a page with the form expecting user/pass
        # Submit user/passwd
        self.g.doc.choose_form( id='loginForm' )
        self.g.doc.set_input( 'UserName', self.usr )
        self.g.doc.set_input( 'Password', self.pwd )
        self.g.submit()

        # Now we have the page with the DUO iframe,
        # get TX and APP values
        re_tx_val = re.compile( "sig_request.: .(TX\|[^:]+):(APP\|[^'\"]+)" )
        match = self.g.doc.rex_search( re_tx_val )
        post_data = {
            'tx': match.group(1),
            'app': match.group(2),
        }
        LOGR.debug( f"tx: {post_data['tx']}" )
        LOGR.debug( f"app: {post_data['app']}" )

        # get "Context" and "AuthMethod"
        self.g.doc.choose_form( id='duo_form' )
        fields = self.g.doc.form_fields()
        LOGR.debug( f'add duo_form fields to post data: {pprint.pformat( fields )}' )
        post_data.update( fields )
        # get "parent"
        self.g.doc.choose_form( id='options' )
        post_data['parent'] = self.g.doc.form.action
        LOGR.debug( f"parent: {post_data['parent']}" )

        # Do the DUO auth
        # ... Duo auth needs "tx" and "parent"; it will return "auth"
        # ... After Duo auth, will need to build sig_response from "auth" + "app"
        # ... and pass it to "parent"
        login_status = self.duo_authenticate( post_data['tx'], post_data['parent'] )

        # Create sig_response from "auth" (from duo) and "app" (from above)
        post_data['auth'] = login_status['authSig']
        sig_response=':'.join( ( post_data['auth'], post_data['app'] ) ) 
        post = {
            'sig_response': sig_response,
            'Context': post_data['Context'],
            'AuthMethod': post_data['AuthMethod']
        }
        # Redirect back to parent (SAML2 SSO)
        self.g.go( post_data['parent'], post=post )

        # Response should be "... press the Continue button once to proceed."
        # .. sets SAMLResponse
        self.g.submit()
        self.g.submit()


    def duo_authenticate( self, tx, parent ):
        g = grab.Grab() #create a new grab instance (don't poison the other one)
        if LOGR.getEffectiveLevel() is logging.DEBUG:
            g.setup( debug=True, log_dir='LOGS.DUO' )
        DUO = {}
        DUO['initialize'] = 'https://verify.uillinois.edu/frame/web/v1/auth'
        DUO['pre_auth'] = 'https://verify.uillinois.edu/frame/devices/preAuth'
        DUO['push'] = 'https://verify.uillinois.edu/frame/devices/authPush_async'
        DUO['status'] = 'https://verify.uillinois.edu/frame/devices/authStatus/'
        DUO['v'] = '2.6'
        # Initialize DUO (get JSESSIONID)
        url_parts = (
            f"{DUO['initialize']}",
            f'?tx={tx}',
            f'&parent={parent}',
            f'&pullStatus=0',
            f"&v={DUO['v']}"
            )
        g.go( ''.join(url_parts) )

        # pre-Auth (get DUO push device id)
        post = {
            'tx': tx,
            'parent': parent,
        }
        g.go( DUO['pre_auth'], post=post )
        auth_string = g.doc.body
        auth_data = json.loads( auth_string )
        LOGR.debug( f'JSON: {json.dumps(auth_data, indent=2)}' )
        # Find default device
        default_device = None
        for dev in auth_data['devices']:
            if dev['defDevice'] is True:
                default_device = dev
                break
        if default_device is None:
            raise UserWarning( 'Did not find a default duo auth device.' )
        LOGR.debug( f'DEFAULT DEVICE: {json.dumps( default_device, indent=2 )}' )

        # Initiate duo auth with default device
        post = {
            'tx': tx,
            'parent': parent,
            'device': default_device
        }
        # manually set content-type for json
        g.setup( headers={'Content-Type': 'application/json', 'charset':'UTF-8'} )
        g.go( DUO['push'], post=json.dumps( post ) )
        LOGR.info( 'Sent DUO authentication request to default device' )

        # Get txid, check status (NOTE: txid has nothing to do with TXval from above)
        txid = json.loads( g.doc.body )['status']
        timestamp=0
        url_parts = [
            DUO['status'],
            txid,
            f'?tx={tx}',
            f'&parent={parent}',
            f'&_={timestamp}'
        ]
        max_tries = 4
        pause = 5
        for count in range(4):
            LOGR.debug( f'Attempt {count} of {max_tries}' )
            timestamp = int( time.time() )
            url_parts[-1] = f'&_={timestamp}'
            url = ''.join( url_parts )
            g.setup( headers={'Content-Type': 'application/json', 'charset':'UTF-8'} )
            g.go( url )
            # check duo auth status
            login_status = json.loads( g.doc.body )
            if login_status['status'] == 'allow':
                break
            LOGR.info( f'sleep {pause} seconds' )
            time.sleep( pause )
        if login_status['status'] != 'allow':
            raise UserWarning( 'DUO authentication failed' )
        else:
            LOGR.info ( 'DUO authentication succeeded' )
        return login_status


if __name__ == '__main__':
    print( 'PyDuo not valid from cmdline' )
