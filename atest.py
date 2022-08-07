import pathlib
import grab
import logging
import netrc
import os
import pprint
import pyduo
#fmt = '%(levelname)s %(message)s'
log_lvl = logging.DEBUG
fmt = '%(levelname)s [%(filename)s:%(funcName)s:%(lineno)s] %(message)s'
logging.basicConfig( level=log_lvl, format=fmt )

# get login,pass from NETRC
netrc_file = os.getenv( 'NETRC', f"{os.environ['HOME']}/.ssh/netrc" )
nrc = netrc.netrc( netrc_file )
login, account, password = nrc.authenticators( 'EXCH' )

auth_url=(
)
#print( auth_url )

# GRAB object and setup
cookies=pathlib.Path( 'cookiefile' )
cookies.touch()
logs=pathlib.Path( 'LOGS' )
logs.mkdir( exist_ok=True )
g = grab.Grab()
g.setup(
    cookiefile=cookies,
    debug=True,
    log_dir=logs,
    )

# 1. auth
g.go( auth_url )
