#!/usr/bin/env bash
# certbot --manual hook for DNS-01 (run as root by certbot). The TXT records are added
# by hand in IONOS; this hook prints them and waits until every IONOS name server
# answers with them. Output goes to /tmp/naza-acme/log (server.sh streams it live).
set -uo pipefail
DIR=/tmp/naza-acme
LOG=$DIR/log
REC=$DIR/records
ZONE=naza-couture.fr
WAIT_MIN=45
out() { printf '%s\n' "$*" >> "$LOG"; }

case "${1:-}" in
auth)
	echo "$CERTBOT_DOMAIN $CERTBOT_VALIDATION" >> "$REC"
	[[ "${CERTBOT_REMAINING_CHALLENGES:-0}" -gt 0 ]] && exit 0

	out ""
	out "################################################################"
	out "#  ДОБАВЬ В IONOS (Домены → $ZONE → DNS → Добавить запись → TXT)"
	out "#  TTL — минимальный. Существующие записи НЕ трогать."
	while read -r d v; do
		sub="${d%"$ZONE"}"; sub="${sub%.}"; host="_acme-challenge${sub:+.$sub}"
		out "#    Тип: TXT   Имя хоста: $host   Значение: $v"
	done < "$REC"
	out "#  Жду появления записей до $WAIT_MIN мин (проверка каждые 30 с)…"
	out "################################################################"

	ns=$(dig +short NS "$ZONE" @1.1.1.1 | sed 's/\.$//')
	[[ -n $ns ]] || { out "Не удалось узнать NS для $ZONE"; exit 1; }
	deadline=$(( $(date +%s) + WAIT_MIN * 60 ))
	while :; do
		missing=""
		while read -r d v; do
			for s in $ns; do
				dig +short TXT "_acme-challenge.$d" @"$s" | tr -d '"' | grep -qxF "$v" || missing+=" $d@$s"
			done
		done < "$REC"
		[[ -z $missing ]] && break
		if (( $(date +%s) > deadline )); then out "Не дождался:$missing"; exit 1; fi
		out "$(date +%H:%M:%S) ещё нет:$missing"
		sleep 30
	done
	out "$(date +%H:%M:%S) Все TXT видны на всех NS IONOS — Let's Encrypt проверяет…"
	sleep 15
	;;
cleanup)
	[[ "${CERTBOT_REMAINING_CHALLENGES:-0}" -gt 0 ]] && exit 0
	out "Проверка закончена. TXT-записи _acme-challenge можно удалить в IONOS (не обязательно)."
	;;
esac
exit 0
