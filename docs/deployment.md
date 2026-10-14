# AWS demo deployment

## Hosting design

The GRC app is a Flask application with writable SQLite state, so the portfolio's S3 + CloudFront static-site stack cannot run it by itself. This demo uses the same AWS account and infrastructure-as-code workflow, with a CloudFormation-managed Lightsail instance instead. Nginx terminates HTTPS and proxies to Gunicorn on loopback. Cloudflare remains authoritative for `davidoneal.dev` and proxies the app subdomain.

CloudFormation is in `infra/aws-lightsail.yaml`; the shell bootstrap is `infra/lightsail-bootstrap.sh`. It creates a Lightsail Ubuntu 24.04 instance using the 1 GB `micro_3_0` bundle, a static IPv4 address, an SSH rule restricted to the administrator's current `/32`, public HTTP/HTTPS rules, and daily automatic snapshots. At current listed pricing the instance bundle is $7/month. Snapshot storage and other account usage can add charges; check the current AWS bill and Lightsail pricing. The instance's system disk contains the SQLite database. Snapshots provide recovery points, but this is not a highly available database or a guarantee against data loss.

## Initial provisioning

The Lightsail SSH key pair must exist in `us-east-2` before CloudFormation creates the host. Keep its private key outside the repository with user-only file permissions. The stack's SSH firewall rule permits that key to be used only from `AdminCidr`.

```powershell
aws cloudformation validate-template --template-body file://infra/aws-lightsail.yaml --region us-east-2
aws cloudformation create-stack --stack-name grc-assurance-engine-demo --template-body file://infra/aws-lightsail.yaml --parameters ParameterKey=AdminCidr,ParameterValue=<your-public-ip>/32 ParameterKey=SshKeyName,ParameterValue=<lightsail-key-name> --region us-east-2
aws cloudformation wait stack-create-complete --stack-name grc-assurance-engine-demo --region us-east-2
aws cloudformation describe-stacks --stack-name grc-assurance-engine-demo --region us-east-2 --query "Stacks[0].Outputs"
```

1. The bootstrap installs the app, Nginx, and Gunicorn, and leaves Nginx returning a setup response. It does not put the demo password into CloudFormation user data.
2. In Cloudflare DNS, add an `A` record for `grc-assurance-engine.labs.davidoneal.dev` pointing to the `PublicIp` stack output. Proxy it through Cloudflare. Do not change the existing `labs.davidoneal.dev` record or apex records.
3. Over SSH, put `DEMO_USERNAME` and a unique, randomly generated `DEMO_PASSWORD` in `/etc/grc-assurance-engine.env`, with root ownership and mode `0600`. Never put these values in Git, CloudFormation parameters, or terminal transcripts. Restart `grc-assurance-engine`.
4. Copy `infra/nginx-site.conf` to `/etc/nginx/sites-available/grc-assurance-engine`, enable it, run `nginx -t`, and reload Nginx. This proxies to Gunicorn only on localhost.
5. Install Certbot and its Nginx plugin, then issue a Let's Encrypt certificate for `grc-assurance-engine.labs.davidoneal.dev` using the Nginx plugin with HTTP-to-HTTPS redirection. Verify that the certificate renewal timer is enabled.
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
