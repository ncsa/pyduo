#!/bin/bash

[[ -f /tmp/firstrun ]] || {
  pip install --upgrade pip
  pip install -r requirements.txt
  touch /tmp/firstrun
  apt update && apt -y install vim less
}

export NETRC='/home/.ssh/netrc'

python atest.py
