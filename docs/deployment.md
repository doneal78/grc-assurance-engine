# Hosted demo deployment

## Prepared target

The current deployment blueprint targets Render and the subdomain `grc-assurance-engine.labs.davidoneal.dev`. Render runs the existing Flask application; Cloudflare remains the DNS provider and can proxy the custom-domain traffic. The app continues to use SQLite, with its database file placed on a 1 GB persistent disk mounted at `/var/data`.

The Render blueprint (`render.yaml`) is configuration only. It does not provision the service, select a billing account, or change DNS. Render requires a paid web-service plan to attach a persistent disk. Current listed pricing for the 0.5 CPU/512 MB Starter service is $7/month, and the 1 GB disk is $0.25/month, for an estimated $7.25/month before taxes or other usage. Check Render's current pricing before provisioning.

## Access control

The hosted configuration sets `REQUIRE_AUTH=true`. The app returns an HTTP Basic challenge for all application routes except `/health`. Keep the `onrender.com` hostname disabled after the custom domain is verified so the custom domain is the only hostname accepted by the service. Use HTTPS for all access.

This is a shared demo password gate, not user accounts, MFA, or production-grade identity management. Use only synthetic data. Do not upload vendor evidence or production records.

## Provisioning sequence

1. Review current Render compute and storage costs and create the service from `render.yaml` in the Render dashboard.
2. Supply a unique demo username and a strong, randomly generated password when Render requests the `DEMO_USERNAME` and `DEMO_PASSWORD` values. Do not commit either value.
3. Wait for the health check and verify that `/` challenges for credentials while `/health` returns the documented status.
4. In Render's service settings, confirm `grc-assurance-engine.labs.davidoneal.dev` as the custom domain and verify the Render subdomain is disabled.
5. Add only the DNS record Render requests for `grc-assurance-engine.labs.davidoneal.dev` in Cloudflare. Do not modify the apex domain or existing `labs` records. Verify DNS and HTTPS from authenticated and unauthenticated browser sessions.
6. Confirm a saved synthetic risk remains after a service restart or redeploy, and confirm the app still requires credentials.

Do not use the public URL until the password is set and these checks are complete. Resource creation, billing, and DNS changes require the owner's approval.

## Local verification

Run `python -m pytest -q` from the repository root. To exercise hosted authentication locally, set `REQUIRE_AUTH=true`, `DEMO_USERNAME`, and `DEMO_PASSWORD` before starting the app. The local `run.py` entry point remains bound to loopback and is not a production server.
