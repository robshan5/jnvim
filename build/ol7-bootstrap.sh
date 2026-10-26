#!/bin/sh
# Enable the Oracle Linux 7 SoftwareCollections repo and install Python 3.8.
set -e
cat > /etc/yum.repos.d/ol7-scl.repo <<'EOF'
[ol7_software_collections]
name=Software Collection Library release 3.0 packages for Oracle Linux 7 (x86_64)
baseurl=https://yum.oracle.com/repo/OracleLinux/OL7/SoftwareCollections/x86_64/
gpgcheck=0
enabled=1
EOF
yum -q -y install rh-python38 rh-python38-python-devel >/dev/null 2>&1 || \
    yum -y install rh-python38 rh-python38-python-devel
. /opt/rh/rh-python38/enable
python3 -V
