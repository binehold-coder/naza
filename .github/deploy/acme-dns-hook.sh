#!/usr/bin/env bash
# certbot --manual hook for DNS-01 (run as root by certbot). Adds/removes the
# _acme-challenge TXT records through the IONOS DNS API and waits until every IONOS
# name server answers with them. Output goes to /tmp/naza-acme/log (streamed by server.sh).
# The API key is in /tmp/naza-acme/key only for the duration of this certbot run.
set -uo pipefail
DIR=/tmp/naza-acme
LOG=$DIR/log
ZONE=naza-couture.fr
WAIT_MIN=20
export IONOS_API_KEY_FILE=$DIR/key
out() { printf '%s\n' "$*" >> "$LOG"; }
name="_acme-challenge.$CERTBOT_DOMAIN"

case "${1:-}" in
auth)
	echo "$CERTBOT_DOMAIN $CERTBOT_VALIDATION" >> "$DIR/records"
	python3 "$DIR/ionos_dns.py" txt-add "$name" "$CERTBOT_VALIDATION" >> "$LOG" 2>&1 \
		|| { out "IONOS API: не удалось добавить TXT $name"; exit 1; }
	[[ "${CERTBOT_REMAINING_CHALLENGES:-0}" -gt 0 ]] && exit 0

	ns=$(dig +short NS "$ZONE" @1.1.1.1 | sed 's/\.$//')
	[[ -n $ns ]] || { out "Не удалось узнать NS для $ZONE"; exit 1; }
	out "Жду TXT на всех NS IONOS: $(echo "$ns" | tr '\n' ' ')"
	deadline=$(( $(date +%s) + WAIT_MIN * 60 ))
	while :; do
		missing=""
		while read -r d v; do
			for s in $ns; do
				dig +short TXT "_acme-challenge.$d" @"$s" | tr -d '"' | grep -qxF "$v" || missing+=" $d@$s"
			done
		done < "$DIR/records"
		[[ -z $missing ]] && break
		if (( $(date +%s) > deadline )); then out "Не дождался:$missing"; exit 1; fi
		out "$(date +%H:%M:%S) ещё нет:$missing"
		sleep 20
	done
	out "$(date +%H:%M:%S) TXT видны на всех NS — Let's Encrypt проверяет…"
	sleep 10
	;;
cleanup)
	python3 "$DIR/ionos_dns.py" txt-del "$name" "$CERTBOT_VALIDATION" >> "$LOG" 2>&1 \
		|| out "IONOS API: не удалось удалить TXT $name (не критично)"
	;;
esac
exit 0
