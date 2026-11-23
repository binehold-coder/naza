# Deploy to IONOS VPS (replaces Vercel)

Status (23 Nov 2026): live on the VPS. DNS zone is at IONOS (nameservers switched back from
`ns*.vercel-dns.com`), `@`/`www` A → 87.106.25.155, certificate renewed via HTTP-01 webroot.

Workflow: `.github/workflows/deploy-server.yml`. Server script: `server.sh`.

- Push to `main` → GitHub Actions runs `build.py`, uploads `preview-site/` over SSH,
  unpacks into `/var/www/naza-releases/<date>-<sha>` and atomically switches the
  symlink `/var/www/naza-couture.fr` (last 5 releases kept). No downtime.
- nginx: `/etc/nginx/sites-available/naza-couture.fr` (marker `managed by naza`).
  HTTP config until the certificate exists, then HTTPS config: everything → `https://www.naza-couture.fr`.
  Every change: `nginx -t` first; on failure the previous config is restored, no reload.
- Certificate: one Let's Encrypt cert for `naza-couture.fr` + `www`, renewed by `certbot.timer`
  via webroot `/var/www/letsencrypt`, deploy hook reloads nginx.
- Telegram bot (`naza-bot`): publishes by merging `content-draft` into `main` → this workflow
  deploys it. The bot waits for a GitHub Deployment with environment `Production`; the workflow
  creates it (in_progress → success/failure). Bot previews (`Preview` deployments of
  `content-draft`, and the test publish branch) still come from Vercel.
- Secrets (repo settings): `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (same values as in `my_budget`),
  `IONOS_API_KEY` (`<prefix>.<secret>` from developer.hosting.ionos.com) for DNS. The key is passed to the
  server only for a DNS-01 run (temp file, deleted after).

Actions (Actions → Deploy to IONOS → Run workflow, or push `ops/<action>-<anything>`):

| action | what |
|---|---|
| `deploy` | build + publish site, nginx, local check (also every push to `main`) |
| `cert-dns` | issue the cert before the DNS switch: DNS-01, TXT records via IONOS API |
| `migrate` | `cert-dns` → `@`/`www` A → 87.106.25.155 via IONOS API (old values in the run annotations) → wait for public DNS → `cert` |
| `cert` | after the switch: cert to HTTP-01 auto-renewal, `certbot renew --dry-run`, `certbot.timer`, checks |
| `status` | DNS, cert, nginx, current release |
| `dns-show` | list the zone records (IONOS API) |

Results are also written as annotations (`::notice::`/`::error::`) on the run page.

Rollback of a release: `sudo ln -sfn /var/www/naza-releases/<older> /var/www/naza-couture.fr.tmp && sudo mv -Tf /var/www/naza-couture.fr.tmp /var/www/naza-couture.fr`.
