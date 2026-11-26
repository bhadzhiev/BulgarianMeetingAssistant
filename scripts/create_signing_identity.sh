#!/bin/sh
# Make a local code signing certificate for builds on this Mac. Run it one time.
# macOS ties a Keychain permission to the app signature. An ad-hoc signature changes with each build,
# so each new build asks for Keychain access again. With this certificate, macOS asks one more time only.
# The certificate stays in the login keychain of this Mac. It is not valid for distribution.
set -eu
name="Atlanta Local Code Signing"
if security find-identity -p codesigning | grep -q "\"$name\""; then
  echo "The certificate \"$name\" already exists."
  exit 0
fi
work=$(mktemp -d)
trap 'rm -rf "$work"' 0
cat > "$work/cfg" <<CONFIG
[req]
distinguished_name=dn
prompt=no
x509_extensions=ext
[dn]
CN=$name
[ext]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature
extendedKeyUsage=critical,codeSigning
CONFIG
# The macOS openssl writes a PKCS#12 file that "security import" can read.
/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -keyout "$work/key.pem" -out "$work/cert.pem" -days 3650 -config "$work/cfg" 2>/dev/null
password=$(/usr/bin/openssl rand -hex 16)
/usr/bin/openssl pkcs12 -export -inkey "$work/key.pem" -in "$work/cert.pem" -out "$work/id.p12" -passout "pass:$password" -name "$name"
security import "$work/id.p12" -k "$HOME/Library/Keychains/login.keychain-db" -P "$password" -T /usr/bin/codesign
echo "Made \"$name\". The next scripts/install_desktop.sh signs the app with it."
