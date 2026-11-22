#!/usr/bin/env bash
# Naza Couture static site on the IONOS VPS. Run by GitHub Actions over SSH from the
# unpacked deploy bundle (/tmp/naza_deploy/bundle). Touches only naza-couture.fr files:
#   /var/www/naza-couture.fr            -> symlink to the current release (atomic switch)
#   /var/www/naza-releases/<release>     last 5 releases kept for rollback
#   /etc/nginx/sites-available/naza-couture.fr (+ symlink in sites-enabled)
#   /etc/letsencrypt/live/naza-couture.fr      one certificate for both names
# Other nginx sites (budget.epoxea.eu, bots) are never edited.
set -euo pipefail

DOMAIN=naza-couture.fr
WWW=www.naza-couture.fr
SERVER_IP=87.106.25.155
ROOT_LINK=/var/www/naza-couture.fr
RELEASES=/var/www/naza-releases
KEEP=5
B="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_CONF=/etc/nginx/sites-available/$DOMAIN
SITE_LINK=/etc/nginx/sites-enabled/$DOMAIN
CERT=/etc/letsencrypt/live/$DOMAIN/fullchain.pem
RENEWAL=/etc/letsencrypt/renewal/$DOMAIN.conf

SUDO=(); [[ $(id -u) == 0 ]] || SUDO=(sudo -n)
say() { printf '\n=== %s\n' "$*"; }
# ::error:: / ::notice:: lines become annotations on the GitHub run (readable without logs)
die() { printf '::error title=server.sh::%s\n' "$*"; exit 1; }
ok() { printf '::notice title=server.sh::%s\n' "$*"; }
have_cert() { "${SUDO[@]}" test -f "$CERT"; }

ensure_dig() {
	command -v dig >/dev/null && return
	echo "Ставлю dig (bind9-dnsutils)"
	"${SUDO[@]}" apt-get install -y -qq bind9-dnsutils >/dev/null
}

# ---------- site files ----------
stage_site() {
	say "Файлы сайта → $ROOT_LINK"
	[[ -f $B/site.tar.gz ]] || die "нет site.tar.gz в бандле"
	if [[ -e $ROOT_LINK && ! -L $ROOT_LINK ]]; then
		die "$ROOT_LINK существует и это не наш symlink — не трогаю"
	fi
	if [[ ! -d $RELEASES ]]; then
		"${SUDO[@]}" mkdir -p "$RELEASES"
		"${SUDO[@]}" chown "$(id -un):$(id -gn)" "$RELEASES"
	fi
	local rel; rel="$RELEASES/$(date +%Y%m%d-%H%M%S)-${REVISION:-manual}"
	mkdir -p "$rel"
	tar -xzf "$B/site.tar.gz" -C "$rel"
	[[ -f $rel/index.html && -f $rel/ua/index.html ]] || die "в сборке нет index.html / ua/index.html"
	echo "${REVISION:-manual}" > "$rel/REVISION.txt"
	find "$rel" -type d -exec chmod 755 {} + && find "$rel" -type f -exec chmod 644 {} +

	# atomic switch: new symlink next to the old one, then rename over it
	"${SUDO[@]}" ln -sfn "$rel" "$ROOT_LINK.tmp"
	"${SUDO[@]}" mv -Tf "$ROOT_LINK.tmp" "$ROOT_LINK"
	ok "Опубликован релиз $(basename "$(readlink "$ROOT_LINK")")"

	# keep the newest $KEEP releases
	ls -1d "$RELEASES"/*/ 2>/dev/null | sort | head -n -"$KEEP" | while read -r old; do
		[[ "${old%/}" == "$(readlink "$ROOT_LINK")" ]] || rm -rf "$old"
	done
}

# ---------- nginx ----------
stage_nginx() {
	local src
	if have_cert; then src=$B/nginx-https.conf; say "nginx: HTTPS-конфиг (сертификат есть)"
	else src=$B/nginx-http.conf; say "nginx: HTTP-конфиг (сертификата пока нет)"; fi

	if [[ -f $SITE_CONF ]] && ! grep -q 'managed by naza' "$SITE_CONF"; then
		die "$SITE_CONF уже кем-то настроен — не перезаписываю"
	fi
	local other
	other=$("${SUDO[@]}" grep -rlE "server_name[^;]*[[:space:]](www\.)?naza-couture\.fr[[:space:];]" \
		/etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | grep -v "/$DOMAIN\$" || true)
	[[ -z $other ]] || die "naza-couture.fr уже объявлен в другом конфиге: $other"

	local backup=""
	if [[ -f $SITE_CONF ]]; then backup=$(mktemp); "${SUDO[@]}" cat "$SITE_CONF" > "$backup"; fi
	"${SUDO[@]}" mkdir -p /var/www/letsencrypt
	"${SUDO[@]}" install -m 644 "$src" "$SITE_CONF"
	"${SUDO[@]}" ln -sfn "$SITE_CONF" "$SITE_LINK"
	if ! "${SUDO[@]}" nginx -t; then
		echo "nginx -t не прошёл — возвращаю прежнее состояние, reload не делаю"
		if [[ -n $backup ]]; then "${SUDO[@]}" install -m 644 "$backup" "$SITE_CONF"
		else "${SUDO[@]}" rm -f "$SITE_LINK" "$SITE_CONF"; fi
		die "конфиг nginx с ошибкой"
	fi
	"${SUDO[@]}" systemctl reload nginx
	sleep 2
	echo "nginx перезагружен"
}

# ---------- local check (through nginx on this server, independent of DNS) ----------
# has <text> <curl args...>: page fetched fully first (grep -q + pipefail would SIGPIPE curl)
# Retries: nginx reload is asynchronous, old workers may answer for a moment.
has() {
	local t=$1 body; shift
	for _ in 1 2 3 4 5; do
		body=$(curl -fsS "$@" 2>/dev/null) && grep -qF "$t" <<<"$body" && return 0
		sleep 1
	done
	return 1
}

stage_check() {
	say "Проверка сайта на этом сервере"
	local code
	if have_cert; then
		local r=(--resolve "$WWW:443:127.0.0.1" --resolve "$DOMAIN:443:127.0.0.1")
		has "Naza Couture" "${r[@]}" "https://$WWW/" || die "https://$WWW/ не отдаёт главную"
		has "Naza" "${r[@]}" "https://$WWW/ua/" || die "https://$WWW/ua/ не отдаётся"
		code=$(curl -s -o /dev/null -w '%{http_code}' "${r[@]}" "https://$WWW/no-such-page")
		[[ $code == 404 ]] || die "несуществующая страница отдаёт $code вместо 404"
		code=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "${r[@]}" "https://$DOMAIN/services.html")
		[[ $code == "301 https://$WWW/services.html" ]] || die "редирект $DOMAIN → $WWW не работает: $code"
		"${SUDO[@]}" openssl x509 -noout -enddate -ext subjectAltName -in "$CERT"
		ok "Проверка на сервере: HTTPS, оба имени, 404, редирект на www — OK"
	else
		for h in "$DOMAIN" "$WWW"; do
			has "Naza Couture" -H "Host: $h" "http://127.0.0.1/" || die "http://$h/ не отдаёт главную"
		done
		code=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $WWW" "http://127.0.0.1/no-such-page")
		[[ $code == 404 ]] || die "несуществующая страница отдаёт $code вместо 404"
		ok "Проверка на сервере: HTTP для обоих имён, 404 — OK"
	fi
}

# ---------- DNS helpers ----------
auth_ns() { dig +short NS "$DOMAIN" @1.1.1.1 | sed 's/\.$//' ; }

dns_report() {
	ensure_dig
	say "DNS сейчас"
	local ns; ns=$(auth_ns | head -1)
	echo "Авторитетный NS: ${ns:-?}"
	for n in "$DOMAIN" "$WWW"; do
		for s in "$ns" 1.1.1.1 8.8.8.8; do
			printf '%-22s @%-18s A=%s CNAME=%s AAAA=%s\n' "$n" "$s" \
				"$(dig +short A "$n" @"$s" | tr '\n' ' ')" \
				"$(dig +short CNAME "$n" @"$s" | tr '\n' ' ')" \
				"$(dig +short AAAA "$n" @"$s" | tr '\n' ' ')"
		done
	done
	echo "CAA: $(dig +short CAA "$DOMAIN" @1.1.1.1 | tr '\n' ' ')"
}

dns_points_here() {
	local ns n s a; ns=$(auth_ns)
	[[ -n $ns ]] || return 1
	for n in "$DOMAIN" "$WWW"; do
		for s in $ns 1.1.1.1 8.8.8.8; do
			a=$(dig +short A "$n" @"$s" | grep -E '^[0-9.]+$' | sort -u | tr '\n' ' ')
			[[ $a == "$SERVER_IP " ]] || { echo "$n @$s → '${a}' (ждём $SERVER_IP)"; return 1; }
			[[ -z $(dig +short AAAA "$n" @"$s") ]] || { echo "$n @$s: есть AAAA — её нужно удалить"; return 1; }
		done
	done
}

check_caa() {
	local caa; caa=$(dig +short CAA "$DOMAIN" @1.1.1.1)
	if [[ -n $caa ]] && ! grep -q letsencrypt.org <<<"$caa"; then
		die "CAA-запись не разрешает Let's Encrypt: $caa"
	fi
}

# ---------- certificate before the DNS switch (DNS-01, TXT records added by hand) ----------
stage_cert_dns() {
	ensure_dig; check_caa
	if have_cert; then echo "Сертификат уже есть — DNS-01 не нужен"; return; fi
	say "Сертификат заранее через DNS-01 (сайт продолжает работать на Vercel)"
	[[ -n ${IONOS_API_KEY:-} ]] || die "нет IONOS_API_KEY (секрет репозитория)"
	local dir=/tmp/naza-acme
	"${SUDO[@]}" rm -rf "$dir"; mkdir -m 700 "$dir"; : > "$dir/log"; chmod 644 "$dir/log"
	install -m 755 "$B/acme-dns-hook.sh" "$dir/hook.sh"
	install -m 644 "$B/ionos_dns.py" "$dir/ionos_dns.py"
	( umask 077; printf '%s' "$IONOS_API_KEY" > "$dir/key" )
	# certbot captures hook output, so the hook writes to $dir/log and we stream it live
	tail -n +1 -F "$dir/log" 2>/dev/null & local tailpid=$!
	local rc=0
	"${SUDO[@]}" certbot certonly --manual --preferred-challenges dns \
		--manual-auth-hook "$dir/hook.sh auth" \
		--manual-cleanup-hook "$dir/hook.sh cleanup" \
		--cert-name "$DOMAIN" -d "$DOMAIN" -d "$WWW" \
		--non-interactive --agree-tos --keep-until-expiring || rc=$?
	sleep 1; kill "$tailpid" 2>/dev/null || true
	"${SUDO[@]}" rm -f "$dir/key"
	[[ $rc == 0 ]] || die "certbot (DNS-01) завершился с ошибкой ($rc)"
	have_cert || die "сертификат не получен"
	ok "Сертификат для обоих имён получен (DNS-01). Автопродление включит action=cert после смены DNS."
}

# ---------- certificate / renewal through HTTP-01 (after the DNS switch) ----------
stage_cert() {
	ensure_dig; check_caa
	say "Проверка, что DNS уже смотрит на этот сервер"
	dns_points_here || die "DNS ещё не обновился — повторить позже"
	echo "DNS OK: оба имени → $SERVER_IP"

	"${SUDO[@]}" mkdir -p /var/www/letsencrypt
	local args=(certonly --webroot -w /var/www/letsencrypt --cert-name "$DOMAIN" -d "$DOMAIN" -d "$WWW"
		--non-interactive --agree-tos --deploy-hook "systemctl reload nginx")
	if have_cert && "${SUDO[@]}" grep -qE '^authenticator *= *webroot' "$RENEWAL"; then
		echo "Сертификат уже продлевается через HTTP-01 (webroot)"
		args+=(--keep-until-expiring)
	elif have_cert; then
		say "Перевожу сертификат на автопродление через HTTP-01 (перевыпуск)"
		args+=(--force-renewal)
	else
		say "Выпуск сертификата через HTTP-01"
	fi
	"${SUDO[@]}" certbot "${args[@]}"
	"${SUDO[@]}" grep -E '^(authenticator|renew_hook|deploy_hook)' "$RENEWAL" || true

	stage_nginx
	stage_check

	say "Автопродление"
	"${SUDO[@]}" systemctl is-active certbot.timer >/dev/null && echo "certbot.timer: active" \
		|| die "certbot.timer не активен"
	systemctl list-timers certbot.timer --no-pager | head -3
	"${SUDO[@]}" certbot renew --dry-run --cert-name "$DOMAIN" --no-random-sleep-on-renew
	ok "Автопродление: certbot.timer активен, renew --dry-run прошёл"
}

stage_status() {
	dns_report
	say "Сертификат"
	if have_cert; then
		"${SUDO[@]}" openssl x509 -noout -enddate -ext subjectAltName -in "$CERT"
		"${SUDO[@]}" grep -E '^authenticator' "$RENEWAL" || true
	else echo "нет"; fi
	say "nginx"
	head -2 "$SITE_CONF" 2>/dev/null || echo "конфига нет"
	echo "Релиз: $(readlink "$ROOT_LINK" 2>/dev/null || echo нет)"
}

case "${1:-}" in
	deploy) stage_site; stage_nginx; stage_check ;;
	cert-dns) stage_cert_dns; stage_nginx; stage_check ;;
	cert) stage_cert ;;
	status) stage_status; stage_check ;;
	*) die "Usage: $0 deploy|cert-dns|cert|status" ;;
esac
