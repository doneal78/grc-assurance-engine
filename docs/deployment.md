# AWS demo deployment

## Current state

As of October 14, 2026, the demo is live and open at `https://grc-assurance.davidoneal.dev`, with no login. The password gate was removed on purpose: every record is synthetic, and the demo is shared by link. The DNS record is proxied through Cloudflare, a Configuration Rule sets SSL to Full (strict) for this hostname only, and Nginx serves HTTPS at the origin with a Cloudflare Origin CA certificate. These checks passed from outside the server on that date: `/health` returned the health JSON over HTTPS, `http://` requests redirected to `https://`, the public certificate was issued by Google Trust Services, and Nginx returned HTTP 429 once a single visitor exceeded the rate limit.

This repository revision changes the health JSON, the bootstrap, and `infra/nginx-site.conf`. Those edits do not change the running host. A person has to install them with the manual runbook below. The October 14 checks describe the host as it was then. They are not a new verification of this revision, and they do not show that the live `/health` body, Nginx limits, service account, or installed commit match this file.

## Hosting design

The app is a Flask application with writable SQLite state, so a static S3 and CloudFront site cannot run it. It runs on a CloudFormation-managed Lightsail instance instead. Cloudflare is the authoritative DNS for `davidoneal.dev` and proxies the app hostname. Nginx terminates HTTPS at the origin using a Cloudflare Origin CA certificate, which only Cloudflare trusts, and proxies requests to Gunicorn on the loopback interface. Cloudflare connects to the origin in Full (strict) mode, set for this hostname only through a Configuration Rule, so other `davidoneal.dev` sites are not affected.

The hostname is a first-level subdomain on purpose. Cloudflare's free Universal SSL certificate covers the root domain and first-level subdomains only, so a deeper name such as `app.labs.davidoneal.dev` would fail the TLS handshake when proxied.

`infra/aws-lightsail.yaml` creates an Ubuntu 24.04 instance on the 1 GB `micro_3_0` bundle, a static IPv4 address, an SSH rule limited to the administrator's `/32`, public HTTP and HTTPS rules, and daily automatic snapshots. At current listed pricing the bundle is $7/month; snapshot storage and other usage can add charges. The SQLite database lives on the instance disk. Snapshots are recovery points, not a highly available database or a guarantee against data loss.

## Initial provisioning

The Lightsail SSH key pair must exist in `us-east-2` before the stack is created. Keep the private key outside the repository with user-only permissions.

`AppRevision` is the full 40-character commit SHA to install. Use a commit that contains this pinned bootstrap. A short SHA or a branch name is rejected. Creating a stack applies the template, including user data. Updating user data on the existing `grc-assurance-engine-demo` instance can replace that instance. Use the manual runbook for the host that is already running, and leave the existing stack unchanged.

```powershell
aws cloudformation validate-template --template-body file://infra/aws-lightsail.yaml --region us-east-2
aws cloudformation create-stack --stack-name grc-assurance-engine-demo --template-body file://infra/aws-lightsail.yaml --parameters ParameterKey=AdminCidr,ParameterValue=<your-public-ip>/32 ParameterKey=SshKeyName,ParameterValue=<lightsail-key-name> ParameterKey=AppRevision,ParameterValue=<40-character-commit-sha> --region us-east-2
aws cloudformation wait stack-create-complete --stack-name grc-assurance-engine-demo --region us-east-2
aws cloudformation describe-stacks --stack-name grc-assurance-engine-demo --region us-east-2 --query "Stacks[0].Outputs"
```

## Setup steps, in order

1. The bootstrap installs the pinned revision, Nginx, and Gunicorn. When no site file exists yet, Nginx returns a setup placeholder. The demo password is never placed in CloudFormation user data. The unit sets `REQUIRE_AUTH=false`.
2. The service runs with `REQUIRE_AUTH=false`, so no login is needed. To put the optional password gate back, set `REQUIRE_AUTH=true` and add `DEMO_USERNAME` and a unique, randomly generated `DEMO_PASSWORD` to `/etc/grc-assurance-engine.env`, owned by root with mode `0600`. Never put these values in Git, CloudFormation parameters, or terminal transcripts.
3. In Cloudflare, create an Origin CA certificate for `grc-assurance.davidoneal.dev`. On the server, save the certificate as `/etc/ssl/cloudflare/grc-assurance.davidoneal.dev.pem` and the private key as `/etc/ssl/cloudflare/grc-assurance.davidoneal.dev.key`, owned by root, with the key at mode `0600`. The private key never goes in Git or transcripts.
4. Copy `infra/nginx-site.conf` to `/etc/nginx/sites-available/grc-assurance-engine`, run `nginx -t`, and reload Nginx. Port 80 redirects to HTTPS, and unknown hostnames are rejected. In this file, `/try/` and `/api/` each allow 20 requests a minute per visitor, and other pages allow 120. The bootstrap does not copy this file over an existing site. The live host keeps its installed Nginx file until this copy and reload.
5. In Cloudflare, add a Configuration Rule that sets SSL to Full (strict) for `grc-assurance.davidoneal.dev`, then add a proxied `A` record for that name pointing to the stack's `PublicIp` output. Do not change the zone-wide SSL mode, the existing `labs.davidoneal.dev` record, or the root records.
6. Verify that `/health` returns HTTP 200 and JSON with `"status": "ok"` and `"database": "reachable"`. Pages load over HTTPS, and an `http://` request redirects to `https://`. Then check the phone-width layout and save a synthetic scenario to the risk register. A database the process cannot read returns HTTP 503 and `"database": "unreachable"`, with no filesystem path and no driver message.

## Updating and rolling back

There is no automated deployment pipeline. Update the running host by hand.

1. Back up the database with SQLite's online backup. From the host:

```bash
sudo sqlite3 /var/lib/grc-assurance/grc_assurance.sqlite3 ".backup /var/lib/grc-assurance/pre-update.sqlite3"
```

2. Install one reviewed commit. The command downloads the bootstrap script from that same commit and passes the SHA. The script refuses a branch name. It records the SHA in `/etc/grc-assurance-revision` after the tree and dependencies are installed. A later re-run without `GRC_REVISION` installs that recorded SHA again.

```bash
curl -fsSL "https://raw.githubusercontent.com/doneal78/grc-assurance-engine/<40-character-sha>/infra/lightsail-bootstrap.sh" -o /tmp/grc-assurance-bootstrap.sh
sudo GRC_REVISION=<40-character-sha> bash /tmp/grc-assurance-bootstrap.sh
```

The script replaces `/opt/grc-assurance-engine` with that tarball. It keeps `.venv` and `instance/`, then reinstalls Python dependencies into `.venv`. It does not delete `/var/lib/grc-assurance/` or `grc_assurance.sqlite3`. It creates the local account `grc-assurance` when that account is missing, gives that account the app tree and the data directory, and restarts `grc-assurance-engine` as that user. SSH stays on the `ubuntu` account. The account is a separate service user. It is not a locked-down sandbox, and the unit keeps `REQUIRE_AUTH=false`.

Before running it on the existing host, confirm `/etc/grc-assurance-engine.env` does not set `REQUIRE_AUTH=true` unless `DEMO_USERNAME` and `DEMO_PASSWORD` are also set. That file overrides the unit. If the service fails to start, the script exits non-zero and the log is `/var/log/grc-assurance-bootstrap.log`. The data directory may already belong to `grc-assurance` at that point. Fix the unit or the env file and re-run the same SHA. Do not delete the SQLite file.

Re-running the script leaves the existing Nginx site file in place. It does not publish the tighter `/api/` limit.

3. Install the Nginx file from the same commit when that file should change, then reload:

```bash
curl -fsSL "https://raw.githubusercontent.com/doneal78/grc-assurance-engine/<40-character-sha>/infra/nginx-site.conf" -o /tmp/grc-assurance-nginx.conf
sudo cp /tmp/grc-assurance-nginx.conf /etc/nginx/sites-available/grc-assurance-engine
sudo nginx -t && sudo systemctl reload nginx
```

4. On the host, `curl -fsS http://127.0.0.1:8000/health` should return `"database": "reachable"`. Check the public HTTPS URL as well. Save nothing but synthetic data.

To roll back, repeat the steps with the previous reviewed SHA. Leave the SQLite file in place. A code rollback does not reverse schema changes already applied to that file. Migrations in this application add columns and rebuild the decisions table in place; they do not drop saved rows.

A failed bootstrap can leave a partial app tree. Re-run it with the same SHA. The log is `/var/log/grc-assurance-bootstrap.log`. That log is a local file. It is not an immutable audit trail.

## Known gaps

### Fixed in this revision's files, still pending on the live host

The running host changes only when a person completes the manual runbook. This repository change did not SSH to the instance, reload Nginx, or update the CloudFormation stack.

| Gap | In this revision | On the live host until the runbook is done |
| --- | --- | --- |
| Bootstrap revision | The script installs a full 40-character SHA from `GRC_REVISION` or `/etc/grc-assurance-revision`. It does not download the moving `main` branch. A new stack's user data passes `AppRevision` and downloads the bootstrap script from that SHA. | The host still runs whatever revision was installed earlier. |
| Stale app files | A re-run deletes app-tree files that are not in the pinned tarball. It keeps `.venv` and `instance/`. The SQLite path stays outside the app tree. | Older files remain until the bootstrap is re-run. |
| Service account | The unit runs as `grc-assurance`, created on the host when missing. The `ubuntu` account remains for SSH. | The running unit still uses `ubuntu` until the bootstrap is re-run. |
| Database readiness | `GET /health` opens the configured SQLite file read-only. Reachable is HTTP 200 and `"database": "reachable"`. Unreachable is HTTP 503 and `"database": "unreachable"`. The body has no path and no driver message. | The live process still serves the previous health JSON until this revision is deployed and restarted. |
| `/api/` rate limit | `infra/nginx-site.conf` limits `/api/` to 20 requests a minute per visitor (burst 10) and 5 requests a second across visitors (burst 20), the same budget as `/try/`. Other pages stay at 120 requests a minute per visitor. | The live Nginx file is unchanged until a person copies this file and reloads Nginx. |

A database result of `reachable` means the file opened read-only and its catalog could be read. It does not validate schema completeness, integrity, disk space, or backups. It does not make the demo production-ready.

### Still open

Daily snapshots are configured and have not been restore-tested. The procedure in Snapshot restore drill is something a person can run. This change did not run it, and there is no recorded result.

There is no login. `REQUIRE_AUTH` stays false on purpose for the open demo. Anyone with the link can use the demo and add synthetic records to the shared risk register. The register must never hold real data.

SQLite supports this single instance only. There is no second host, no replica, and no highly available database.

There is no automated deployment pipeline. The manual runbook above is the update path.

The dedicated account, the read-only health check, and the tighter `/api/` limit are ordinary host hygiene. They are not a production hardening claim.

### Unchanged product behavior

File import reads an uploaded CSV, `.xlsx`, or simulated ServiceNow JSON/CSV file. It does not connect to ServiceNow. Preview and confirm do not write. The result page can save one synthetic vendor into the shared risk register when the visitor checks the box and records a disposition. Nginx's default upload limit is 1 MB, which is above the application's 256 KB cap.

`POST /api/v1/intake/assess` is open because `REQUIRE_AUTH` is false. Assess alone does not write. A body with `persist` true and a human disposition does write a synthetic row to the shared register. Do not send real vendor data. See `docs/bot-contract.md`.

The dashboard counts whatever synthetic rows are in the shared SQLite file. Those counts are observed for that file. They are not a baseline study, a monthly rate, or cash savings. The cost panel remains the illustrative formula in `app/data/cost_assumptions.json`. Human handling time is still unmeasured. A same-second intake and disposition is a 0-second elapsed span in that file, which is the clock record of the save.

## Snapshot restore drill

This drill has not been executed. Running it creates a second Lightsail instance and can add charges. Do it only with an account owner who accepts that cost.

1. In Lightsail for `us-east-2`, open instance `grc-assurance-engine-demo` and note the latest automatic snapshot. The template requests a daily snapshot at 08:00 UTC.
2. Create a new instance from that snapshot. Leave the production static IP and the DNS name on the original instance.
3. On the copy, check `systemctl is-active grc-assurance-engine`, request `http://127.0.0.1:8000/health`, and confirm a known synthetic row is still in `/var/lib/grc-assurance/grc_assurance.sqlite3`. After this revision is installed, the health JSON includes `"database": "reachable"` when the file can be read. A copy made from an older snapshot still has the health JSON from that snapshot.
4. Delete the copy when the check is finished. Record the date and the result somewhere outside this repository. Until that record exists, treat snapshots as untested recovery points.

## Operations and limitations

The instance and its daily snapshots incur AWS charges, so set an account budget alert. A snapshot is a recovery point for this one disk. It becomes a tested recovery path only after the drill above has been run and recorded. SQLite supports this single instance only; do not scale the design horizontally or use it for real vendor records. There is no login: anyone with the link can use the demo and add synthetic records to the shared risk register, so it must never hold real data. Nginx rate limits are whatever site file is installed on the host. The repository file limits `/try/` and `/api/` more tightly than other pages, and the live file matches that only after a person installs it. `/health` in this revision checks that the SQLite file can be read. That check is not a production readiness test. The demo is an illustrative portfolio prototype, not a production GRC service or certification tool.

## Local verification

Run `python -m pytest` from the repository root. The local `run.py` entry point stays bound to loopback and is not a production server.
