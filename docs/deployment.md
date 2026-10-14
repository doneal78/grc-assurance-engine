# AWS demo deployment

## Hosting design

The GRC app is a Flask application with writable SQLite state, so the portfolio's S3 + CloudFront static-site stack cannot run it by itself. This demo uses the same AWS account and infrastructure-as-code workflow, with an AWS CloudFormation-managed Lightsail instance instead. Nginx terminates HTTPS and proxies to Gunicorn on loopback. Cloudflare remains authoritative for `davidoneal.dev` and proxies the app subdomain.

CloudFormation is in `infra/aws-lightsail.yaml`. It creates a Lightsail Ubuntu 24.04 instance using the 1 GB `micro_3_0` bundle, a static IPv4 address, an SSH rule restricted to the administrator's current `/32`, public HTTP/HTTPS rules, and daily automatic snapshots. At current listed pricing the instance bundle is $7/month. Snapshot storage and any other account usage can add charges; check the current AWS bill and Lightsail pricing. The instance's system disk contains the SQLite database. Snapshots provide recovery points, but this is not a highly available database or a guarantee against data loss.

## Initial provisioning

1. Validate the CloudFormation template and create stack `grc-assurance-engine-demo` in `us-east-2`. Supply `AdminCidr` as the public IPv4 address from which SSH will be administered, in `/32` notation. The template starts the instance in a closed setup state and does not contain the demo password.
2. Wait for CloudFormation to complete and read the `PublicIp` stack output.
3. In Cloudflare DNS, add an `A` record for `grc-assurance-engine.labs.davidoneal.dev` pointing to that static IP. Proxy it through Cloudflare. Do not change the existing `labs.davidoneal.dev` record or apex records.
4. Connect to the Ubuntu instance using its Lightsail SSH key. Set `DEMO_USERNAME` and a unique, randomly generated `DEMO_PASSWORD` in `/etc/grc-assurance-engine.env`, with file permissions `0600`. Never put these values in Git, CloudFormation parameters, or terminal transcripts. Restart `grc-assurance-engine`.
5. Replace the Nginx setup response with the reverse proxy configuration for the app domain, then issue a Let's Encrypt certificate with Certbot's Nginx plugin for `grc-assurance-engine.labs.davidoneal.dev` and enable HTTP-to-HTTPS redirection. Verify that the certificate renewal timer is enabled.
6. Confirm `/health` returns the health JSON over HTTPS, unauthenticated page requests receive HTTP 401, and authenticated requests render the dashboard. Check phone-width layout and save a synthetic scenario to the risk register.

The AWS CloudFormation template controls the Lightsail firewall. Do not expose Gunicorn's port 8000 publicly. SSH should remain limited to the administrator's current address. The app's Basic Auth gate protects every page except `/health`; use a unique demo password and synthetic data only.

## Updating the app

The initial bootstrap downloads the public `main` branch and installs the dependencies. For a code update, deploy a reviewed Git revision to `/opt/grc-assurance-engine`, reinstall requirements if they changed, and restart the `grc-assurance-engine` systemd service. Do not replace or delete `/var/lib/grc-assurance/grc_assurance.sqlite3` during an app update. The demo currently has no automated CI/CD deployment workflow.

## Operations and limitations

- The Lightsail instance and daily snapshots incur AWS charges. Snapshot storage is billed separately. Monitor AWS billing and set an account budget alert.
- A Lightsail instance snapshot is a recovery aid. Verify that a restore procedure works before relying on it; the prototype has no tested disaster-recovery guarantee.
- SQLite is used by one app instance only. Do not scale this design horizontally or use it for production/vendor records.
- HTTP Basic authentication is a shared password gate. It is not MFA, individual user accounts, or a production identity system.
- The health endpoint does not check database readiness and remains unauthenticated for the host health check.
- The demo remains an illustrative portfolio prototype, not a production GRC service or certification tool.

## Local verification

Run `python -m pytest` from the repository root. The local `run.py` entry point remains bound to loopback and is not a production server.
