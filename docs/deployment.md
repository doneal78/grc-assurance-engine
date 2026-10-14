# AWS demo deployment

## Current state

As of October 14, 2026, the Lightsail instance is running, and the application answers its health check when requested directly at the origin. The public hostname, `grc-assurance.davidoneal.dev`, has no DNS record yet, and HTTPS is not configured. The demo is not ready to share. Do not use or share the demo password until HTTPS has been verified.

## Hosting design

The app is a Flask application with writable SQLite state, so a static S3 and CloudFront site cannot run it. It runs on a CloudFormation-managed Lightsail instance instead. Cloudflare is the authoritative DNS for `davidoneal.dev` and will proxy the app hostname. Nginx will terminate HTTPS at the origin using a Cloudflare Origin CA certificate, which only Cloudflare trusts, and proxy requests to Gunicorn on the loopback interface. Cloudflare will connect to the origin in Full (strict) mode, set for this hostname only through a Configuration Rule, so other `davidoneal.dev` sites are not affected.

The hostname is a first-level subdomain on purpose. Cloudflare's free Universal SSL certificate covers the root domain and first-level subdomains only, so a deeper name such as `app.labs.davidoneal.dev` would fail the TLS handshake when proxied.

`infra/aws-lightsail.yaml` creates an Ubuntu 24.04 instance on the 1 GB `micro_3_0` bundle, a static IPv4 address, an SSH rule limited to the administrator's `/32`, public HTTP and HTTPS rules, and daily automatic snapshots. At current listed pricing the bundle is $7/month; snapshot storage and other usage can add charges. The SQLite database lives on the instance disk. Snapshots are recovery points, not a highly available database or a guarantee against data loss.

## Initial provisioning

The Lightsail SSH key pair must exist in `us-east-2` before the stack is created. Keep the private key outside the repository with user-only permissions.

```powershell
aws cloudformation validate-template --template-body file://infra/aws-lightsail.yaml --region us-east-2
aws cloudformation create-stack --stack-name grc-assurance-engine-demo --template-body file://infra/aws-lightsail.yaml --parameters ParameterKey=AdminCidr,ParameterValue=<your-public-ip>/32 ParameterKey=SshKeyName,ParameterValue=<lightsail-key-name> --region us-east-2
aws cloudformation wait stack-create-complete --stack-name grc-assurance-engine-demo --region us-east-2
aws cloudformation describe-stacks --stack-name grc-assurance-engine-demo --region us-east-2 --query "Stacks[0].Outputs"
```

## Setup steps, in order

1. The bootstrap installs the app, Nginx, and Gunicorn, and leaves Nginx returning a setup placeholder. The demo password is never placed in CloudFormation user data.
2. Over SSH, put `DEMO_USERNAME` and a unique, randomly generated `DEMO_PASSWORD` in `/etc/grc-assurance-engine.env`, owned by root with mode `0600`. Never put these values in Git, CloudFormation parameters, or terminal transcripts. Restart `grc-assurance-engine`.
3. In Cloudflare, create an Origin CA certificate for `grc-assurance.davidoneal.dev`. On the server, save the certificate as `/etc/ssl/cloudflare/grc-assurance.davidoneal.dev.pem` and the private key as `/etc/ssl/cloudflare/grc-assurance.davidoneal.dev.key`, owned by root, with the key at mode `0600`. The private key never goes in Git or transcripts.
4. Copy `infra/nginx-site.conf` to `/etc/nginx/sites-available/grc-assurance-engine`, run `nginx -t`, and reload Nginx. Port 80 redirects to HTTPS, and unknown hostnames are rejected.
5. In Cloudflare, add a Configuration Rule that sets SSL to Full (strict) for `grc-assurance.davidoneal.dev`, then add a proxied `A` record for that name pointing to the stack's `PublicIp` output. Do not change the zone-wide SSL mode, the existing `labs.davidoneal.dev` record, or the root records.
6. Verify that `/health` returns the health JSON over HTTPS, an unauthenticated page request returns HTTP 401, and an `http://` request redirects to `https://`. Only then share the password, sign in, check the phone-width layout, and save a synthetic scenario to the risk register.

## Updating and rolling back

Before any update, make a copy of the database with SQLite's online backup, for example the `sqlite3` command-line tool's `.backup` command. To update, deploy a reviewed Git revision to `/opt/grc-assurance-engine`, reinstall requirements if they changed, and restart `grc-assurance-engine`. To roll back, deploy the previous reviewed revision the same way. Never replace or delete `/var/lib/grc-assurance/grc_assurance.sqlite3` during an update. There is no automated deployment pipeline.

## Known gaps

The bootstrap downloads the current `main` branch rather than a pinned revision. The service runs as the default `ubuntu` user rather than a dedicated account. Re-running the bootstrap keeps the live Nginx site but can leave files from older revisions in place. These are tracked for a follow-up change.

## Operations and limitations

The instance and its daily snapshots incur AWS charges, so set an account budget alert. A snapshot is only a recovery aid until a restore has been tested. SQLite supports this single instance only; do not scale the design horizontally or use it for real vendor records. HTTP Basic authentication is one shared password gate, not MFA, individual accounts, or a production identity system. The health endpoint does not check database readiness and stays unauthenticated for host health checks. The demo is an illustrative portfolio prototype, not a production GRC service or certification tool.

## Local verification

Run `python -m pytest` from the repository root. The local `run.py` entry point stays bound to loopback and is not a production server.
