# Deploy to IONOS VPS (replaces Vercel)

Workflow: `.github/workflows/deploy-server.yml`. Server script: `server.sh`.

- Push to `main` → GitHub Actions runs `build.py`, uploads `preview-site/` over SSH,
  unpacks into `/var/www/naza-releases/<date>-<sha>` and atomically switches the
  symlink `/var/www/naza-couture.fr` (last 5 releases kept). No downtime.
- nginx: `/etc/nginx/sites-available/naza-couture.fr` (marker `managed by naza`).
  HTTP config until the certificate exists, then HTTPS config: everything → `https://www.naza-couture.fr`.
  Every change: `nginx -t` first; on failure the previous config is restored, no reload.
- Certificate: one Let's Encrypt cert for `naza-couture.fr` + `www`, renewed by `certbot.timer`
  via webroot `/var/www/letsencrypt`, deploy hook reloads nginx.
- Secrets (repo settings): `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` — same values as in `my_budget`.

Actions (Actions → Deploy to IONOS → Run workflow, or push `ops/<action>-<anything>`):

| action | what |
|---|---|
| `deploy` | build + publish site, nginx, local check |
| `cert-dns` | issue the cert before the DNS switch (DNS-01): the log prints two TXT records to add in IONOS, waits up to 45 min |
| `cert` | after the DNS switch: switch the cert to HTTP-01 auto-renewal, `certbot renew --dry-run`, check `certbot.timer` |
| `status` | DNS, cert, nginx, current release |

Rollback: `sudo ln -sfn /var/www/naza-releases/<older> /var/www/naza-couture.fr.tmp && sudo mv -Tf /var/www/naza-couture.fr.tmp /var/www/naza-couture.fr`.
