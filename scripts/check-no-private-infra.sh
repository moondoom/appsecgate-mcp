#!/usr/bin/env bash
set -euo pipefail

IP_PATTERN='\b(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3})\b'
P1="mg""mt"
P2="mg""mt-ho""st"
P3="llm-""host"
P4="runner-""host"
P5="appsecgate-""lab"
HOST_PATTERN="\\b(${P1}|${P3}|${P4}|[a-z0-9-]+\\.(local|internal|lan|home))\\b"
CRED_PATTERN="(Bearer[[:space:]]+[A-Za-z0-9._~+/-]{20,}|(api[_-]?key|token|password|client_secret)[[:space:]]*[:=][[:space:]]*['\"]?[A-Za-z0-9/_+.-]{8,})"

FAIL=0
FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.(md|py|yaml|yml|json|toml|sh)$' || true)

for f in $FILES; do
  [[ -f "$f" ]] || continue
  SANITIZED=$(sed -E "s/${P5}//g; s/<(${P3}|${P2}|${P4}|private-cidr|project-id|registry)>//g" "$f")
  LINE=$(printf '%s\n' "$SANITIZED" | grep -nE "$IP_PATTERN" | cut -d: -f1 | head -1 || true)
  if [[ -n "$LINE" ]]; then
    echo "ERROR: RFC1918 address in $f:$LINE — see docs/adr/README.md"
    FAIL=1
  fi
  LINE=$(printf '%s\n' "$SANITIZED" | grep -niE "$HOST_PATTERN" | cut -d: -f1 | head -1 || true)
  if [[ -n "$LINE" ]]; then
    echo "ERROR: raw internal hostname in $f:$LINE — see docs/adr/README.md"
    FAIL=1
  fi
  LINE=$(printf '%s\n' "$SANITIZED" | grep -niE "$CRED_PATTERN" | cut -d: -f1 | head -1 || true)
  if [[ -n "$LINE" ]]; then
    echo "ERROR: possible credential in $f:$LINE — see docs/adr/README.md"
    FAIL=1
  fi
done

exit "$FAIL"
