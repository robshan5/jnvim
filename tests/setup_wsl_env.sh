#!/bin/sh
set -e
cd /root/jnvim
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q jupyter_client ipykernel
python -m ipykernel install --user --name python3 >/dev/null 2>&1 || true
python -c 'import jupyter_client, ipykernel; print("deps ok", jupyter_client.__version__, ipykernel.__version__)'
