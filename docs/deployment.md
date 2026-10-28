# AWS demo deployment

## Current state

As of October 14, 2026, the demo is live and open at `https://grc-assurance.davidoneal.dev`, with no login. The password gate was removed on purpose: every record is synthetic, and the demo is shared by link. The DNS record is proxied through Cloudflare, a Configuration Rule sets SSL to Full (strict) for this hostname only, and Nginx serves HTTPS at the origin with a Cloudflare Origin CA certificate. These checks passed from outside the server on that date: `/health` returned the health JSON over HTTPS, `http://` requests redirected to `https://`, the public certificate was issued by Google Trust Services, and Nginx returned HTTP 429 once a single visitor exceeded the rate limit.

`infra/deploy-app-revision.sh` installs one full commit SHA on a host that already has the unit, the virtualenv, and the database. Merge `8dcfea2139ba86134697fe83fb4f64734e3155ce` was installed that way. Local `/health` passed, and `/etc/grc-assurance-revision` was written with that SHA. The process then exited non-zero: the EXIT trap expanded the function-local name `tarball` after `main` returned, and `set -u` reported it as an unbound variable. The `sqlite3` CLI was not on the host until it was installed for that run. curl and python3 were already there. This follow-up keeps the tarball path in a global for that trap, and it adds the `sqlite3` package to the bootstrap install line. Committing it does not install it. This change did not SSH to the instance, did not create GitHub secrets, and did not change the CloudFormation stack. The October 14 checks describe the host as it was then. They are not a verification of this follow-up.

## Hosting design

The app is a Flask application with writable SQLite state, so a static S3 and CloudFront site cannot run it. It runs on a CloudFormation-managed Lightsail instance instead. Cloudflare is the authoritative DNS for `davidoneal.dev` and proxies the app hostname. Nginx terminates HTTPS at the origin using a Cloudflare Origin CA certificate, which only Cloudflare trusts, and proxies requests to Gunicorn on the loopback interface. Cloudflare connects to the origin in Full (strict) mode, set for this hostname only through a Configuration Rule, so other `davidoneal.dev` sites are not affected.

The hostname is a first-level subdomain on purpose. Cloudflare's free Universal SSL certificate covers the root domain and first-level subdomains only, so a deeper name such as `app.labs.davidoneal.dev` would fail the TLS handshake when proxied.

`infra/aws-lightsail.yaml` creates an Ubuntu 24.04 instance on the 1 GB `micro_3_0` bundle, a static IPv4 address, an SSH rule limited to the administrator's `/32`, public HTTP and HTTPS rules, and daily automatic snapshots. At current listed pricing the bundle is $7/month; snapshot storage and other usage can add charges. The SQLite database lives on the instance disk. Snapshots are recovery points, not a highly available database or a guarantee against data loss.

## Initial provisioning

The Lightsail SSH key pair must exist in `us-east-2` before the stack is created. Keep the private key outside the repository with user-only permissions.

`AppRevision` is the full 40-character commit SHA to install. Use a commit that contains this pinned bootstrap. A short SHA or a branch name is rejected. Creating a stack applies the template, including user data. Updating user data on the existing `grc-assurance-engine-demo` instance can replace that instance. For the host that is already running, install a reviewed SHA with `infra/deploy-app-revision.sh`, described under Updating and rolling back. Leave the existing stack unchanged.

```powershell
aws cloudformation validate-template --template-body file://infra/aws-lightsail.yaml --region us-east-2
aws cloudformation create-stack --stack-name grc-assurance-engine-demo --template-body file://infra/aws-lightsail.yaml --parameters ParameterKey=AdminCidr,ParameterValue=<your-public-ip>/32 ParameterKey=SshKeyName,ParameterValue=<lightsail-key-name> ParameterKey=AppRevision,ParameterValue=<40-character-commit-sha> --region us-east-2
aws cloudformation wait stack-create-complete --stack-name grc-assurance-engine-demo --region us-east-2
aws cloudformation describe-stacks --stack-name grc-assurance-engine-demo --region us-east-2 --query "Stacks[0].Outputs"
```

## Setup steps, in order

1. The bootstrap installs the pinned revision, Nginx, Gunicorn, and the `sqlite3` CLI. When no site file exists yet, Nginx returns a setup placeholder. The demo password is never placed in CloudFormation user data. The unit sets `REQUIRE_AUTH=false`.
2. The service runs with `REQUIRE_AUTH=false`, so no login is needed. To put the optional password gate back, set `REQUIRE_AUTH=true` and add `DEMO_USERNAME` and a unique, randomly generated `DEMO_PASSWORD` to `/etc/grc-assurance-engine.env`, owned by root with mode `0600`. Never put these values in Git, CloudFormation parameters, or terminal transcripts.
3. In Cloudflare, create an Origin CA certificate for `grc-assurance.davidoneal.dev`. On the server, save the certificate as `/etc/ssl/cloudflare/grc-assurance.davidoneal.dev.pem` and the private key as `/etc/ssl/cloudflare/grc-assurance.davidoneal.dev.key`, owned by root, with the key at mode `0600`. The private key never goes in Git or transcripts.
4. Copy `infra/nginx-site.conf` to `/etc/nginx/sites-available/grc-assurance-engine`, run `nginx -t`, and reload Nginx. Port 80 redirects to HTTPS, and unknown hostnames are rejected. In this file, `/try/` and `/api/` each allow 20 requests a minute per visitor, and other pages allow 120. The bootstrap does not copy this file over an existing site. Later updates copy it only when `deploy-app-revision.sh` is run with `--update-nginx`. The default deploy leaves the installed site file alone.
5. In Cloudflare, add a Configuration Rule that sets SSL to Full (strict) for `grc-assurance.davidoneal.dev`, then add a proxied `A` record for that name pointing to the stack's `PublicIp` output. Do not change the zone-wide SSL mode, the existing `labs.davidoneal.dev` record, or the root records.
6. Verify that `/health` returns HTTP 200 and JSON with `"status": "ok"` and `"database": "reachable"`. Pages load over HTTPS, and an `http://` request redirects to `https://`. Then check the phone-width layout and save a synthetic scenario to the risk register. A database the process cannot read returns HTTP 503 and `"database": "unreachable"`, with no filesystem path and no driver message.

## Updating and rolling back

Routine updates use `infra/deploy-app-revision.sh`. It is the app-revision path for a host that already has the systemd unit, `/opt/grc-assurance-engine/.venv`, and `/var/lib/grc-assurance/grc_assurance.sqlite3`.

`infra/lightsail-bootstrap.sh` remains the first-install path. A re-run of the bootstrap also runs `apt-get`, creates the `grc-assurance` account when it is missing, rewrites the systemd unit, and reloads Nginx without replacing an existing site file. It does not back up SQLite and it does not check `/health`. Use it when the unit or the service account still has to be created. Do not use it as the ordinary way to install a new commit on the host that is already serving the demo.

The app-revision script:

- Requires `--revision` or `GRC_REVISION` to be a full 40-character commit SHA. A branch name or a short SHA is refused. It does not read `/etc/grc-assurance-revision` to decide what to install. The bootstrap still does that on a re-run with no `GRC_REVISION`.
- Backs up the live SQLite file with the `sqlite3` `.backup` command, which uses SQLite's online backup API, before it changes the app tree. The CLI has to be on `PATH`. The script does not install OS packages and does not skip the backup when `sqlite3` is missing. Each backup is a new file under `/var/lib/grc-assurance/backups/`. The script does not delete old backups, and it does not delete `/var/lib/grc-assurance/` or `grc_assurance.sqlite3`. Those files are on the same disk as the demo. They are not a substitute for the Lightsail snapshot, and the snapshot restore drill below is still untested.
- Downloads `https://github.com/doneal78/grc-assurance-engine/archive/<sha>.tar.gz` and replaces `/opt/grc-assurance-engine` through the bootstrap's `replace_app_tree`. That keeps `.venv` and `instance/`.
- Reinstalls Python dependencies with the existing `.venv`. It does not create the virtualenv.
- Restarts `grc-assurance-engine` as the `User=` already set on the unit. It does not create an account and it does not rewrite the unit. If the unit still runs as `ubuntu`, it stays `ubuntu`.
- Writes the SHA to `/etc/grc-assurance-revision`, the same file the bootstrap uses, only after `http://127.0.0.1:8000/health` returns `"status":"ok"` and `"database":"reachable"`. There is no `DEPLOYED_COMMIT` file. A failed health check leaves the previous pin in place even if the tree on disk already changed. Re-run the previous SHA to put that tree back. Do not delete the SQLite file.
- Leaves Nginx alone unless `--update-nginx` is set. That flag installs `infra/nginx-site.conf` from the same tarball, runs `nginx -t`, and reloads. If `nginx -t` fails, the previous site file is restored and Nginx is not reloaded. The script does not create `/etc/nginx/sites-available/grc-assurance-engine` when it is missing.

The script refuses to restart when `/etc/grc-assurance-engine.env` sets `REQUIRE_AUTH=true` without a non-empty `DEMO_USERNAME` and `DEMO_PASSWORD`. It does not print those values. The unit sets `REQUIRE_AUTH=false`. The env file overrides the unit. The open demo should keep the gate off.

Run this on the host, in an SSH session that can already reach the instance. Replace the placeholder with the full SHA. The SHA has to be a commit that contains `infra/deploy-app-revision.sh`.

```bash
sudo bash -c 'set -euo pipefail
SHA=replace-with-40-character-sha
work=$(mktemp -d)
trap "rm -rf -- \"\$work\"" EXIT
curl -fsSL "https://github.com/doneal78/grc-assurance-engine/archive/${SHA}.tar.gz" -o "$work/src.tar.gz"
tar -xzf "$work/src.tar.gz" -C "$work" --strip-components=1
bash "$work/infra/deploy-app-revision.sh" --revision "$SHA"'
```

Add `--update-nginx` immediately after `"$SHA"`, before the closing quote, only when the site file from that same SHA should replace `/etc/nginx/sites-available/grc-assurance-engine`. The symlink in `sites-enabled` stays as it is.

After the script is on the host, this shorter command runs the copy that was installed with the previous SHA. Use it to roll back to a commit that does not contain the script. The script logic is then the copy you invoked, and the app tree is still the tarball for the SHA you pass.

```bash
sudo bash /opt/grc-assurance-engine/infra/deploy-app-revision.sh --revision replace-with-40-character-sha
```

The log is `/var/log/grc-assurance-deploy.log`. A second deploy waits on `/var/lock/grc-assurance-deploy.lock`. The log and the lock are local files. They are not an immutable audit trail. The online backup uses the `sqlite3` CLI. `lightsail-bootstrap.sh` installs that package with the other first-install packages. A host built before that package was on the install line needs `sudo apt-get install -y sqlite3` once. The app-revision script still stops, before it changes the app tree, if the CLI is not installed. It does not skip the backup. If the health check fails, the log names the backup path. Fix the unit or the env file and re-run the same SHA, or re-run the previous SHA. A code rollback does not reverse schema changes already applied to the SQLite file. Migrations in this application add columns and rebuild the decisions table in place; they do not drop saved rows. A non-zero exit after the pin file is written can be the EXIT trap rather than a failed health check. The trap now stores the tarball path outside `main`, so a finished deploy can return 0.

Check the public HTTPS URL after the local health check succeeds. Save nothing but synthetic data.

### GitHub Actions

`.github/workflows/deploy-lightsail.yml` is `workflow_dispatch` only. It does not run on a push or a pull request. The inputs are the same SHA and an optional Nginx boolean. The workflow copies `deploy-app-revision.sh` and `lightsail-bootstrap.sh` from the workflow commit, then the script on the host downloads the application tarball for the SHA. Dispatch it from the branch whose script you want to run, and pass the application SHA as the input. That can be an older SHA that does not contain the script.

The job SSHes only when these repository secrets exist. This repository does not contain their values, and this change did not create them. An empty secret fails the job before any SSH connection.

| Secret | Required | What to store |
| --- | --- | --- |
| `LIGHTSAIL_SSH_KEY` | yes | Private key for the Lightsail SSH account, as a PEM, including line breaks. Not the Lightsail key-pair name. |
| `LIGHTSAIL_HOST` | yes | Static IP of the instance. Not `grc-assurance.davidoneal.dev`. Cloudflare proxies that name to Nginx, and it does not answer SSH. |
| `LIGHTSAIL_KNOWN_HOSTS` | yes | Output of `ssh-keyscan -H <static-ip>` from a machine that can already reach the host. The workflow uses that file and does not accept a different key. |
| `LIGHTSAIL_SSH_USER` | no | SSH account. The default is `ubuntu`. That account needs passwordless `sudo`. |

The Lightsail firewall allows SSH only from the administrator `/32` in the CloudFormation `AdminCidr` parameter. A GitHub-hosted runner uses a different address. This workflow does not change that rule, and it does not open port 22. Until SSH from the runner is allowed, a dispatch that has the secrets still fails at the SSH step. The host command above does not have that limit, because it runs inside a session that is already allowed. No deploy has been run from Actions for this change.

## Known gaps

### Host state after the `8dcfea2139ba86134697fe83fb4f64734e3155ce` dogfood

That install used the app-revision script. It does not rewrite the systemd unit, and it does not reload Nginx unless `--update-nginx` is set. The reported run did not include an Nginx change. This follow-up was not part of that install. Committing this follow-up did not SSH to the instance, reload Nginx, or update the CloudFormation stack.

| Gap | In the repository | On the live host after that dogfood |
| --- | --- | --- |
| Installed revision | App updates install one full SHA and record it in `/etc/grc-assurance-revision` only after local `/health` passes. | The pin file was written with `8dcfea2139ba86134697fe83fb4f64734e3155ce`. This follow-up is not installed yet. |
| Stale app files | A deploy deletes app-tree files that are not in the pinned tarball. It keeps `.venv` and `instance/`. The SQLite path stays outside the app tree. | That run replaced the app tree and kept `.venv` and `instance/`. |
| Service account | The bootstrap unit runs as `grc-assurance`, created on the host when missing. The `ubuntu` account remains for SSH. The app-revision script does not change `User=`. | The unit still uses whatever account it had before that run. |
| Database readiness | `GET /health` opens the configured SQLite file read-only. Reachable is HTTP 200 and `"database": "reachable"`. Unreachable is HTTP 503 and `"database": "unreachable"`. The body has no path and no driver message. | Local `/health` passed, which requires `"status":"ok"` and `"database":"reachable"`. |
| Deploy exit status | The EXIT trap keeps the downloaded tarball path in `CLEANUP_TAR_FILE`, which is not a function local, so a finished `main` can return 0 under `set -u`. | That run exited non-zero after the pin was written, with `tarball: unbound variable`. |
| `sqlite3` CLI | The bootstrap installs the `sqlite3` package. The app-revision script stops if the CLI is missing and does not skip the backup. | The package was missing. It was installed on the host before the health check passed. This follow-up does not re-run the bootstrap. |
| `/api/` rate limit | `infra/nginx-site.conf` limits `/api/` to 20 requests a minute per visitor (burst 10) and 5 requests a second across visitors (burst 20), the same budget as `/try/`. Other pages stay at 120 requests a minute per visitor. | The reported run did not include `--update-nginx`. The live site file changes only when that flag is used or the file is copied by hand. |

A database result of `reachable` means the file opened read-only and its catalog could be read. It does not validate schema completeness, integrity, disk space, or backups. It does not make the demo production-ready.

### Still open

Daily snapshots are configured and have not been restore-tested. The procedure in Snapshot restore drill is something a person can run. This change did not run it, and there is no recorded result.

There is no login. `REQUIRE_AUTH` stays false on purpose for the open demo. Anyone with the link can use the demo and add synthetic records to the shared risk register. The register must never hold real data.

SQLite supports this single instance only. There is no second host, no replica, and no highly available database.

The app-revision script and the manual workflow are the update path for a host that is already bootstrapped. The workflow does not run on push. It cannot SSH until the secrets in Updating and rolling back exist, and the instance SSH rule is still the administrator `/32`. Nginx changes only when `--update-nginx` is passed. The bootstrap remains the first-install path.

The dedicated account, the read-only health check, and the tighter `/api/` limit are ordinary host hygiene. They are not a production hardening claim.

### Unchanged product behavior

File import reads an uploaded CSV, `.xlsx`, or simulated ServiceNow JSON/CSV file. It does not connect to ServiceNow. Preview and confirm do not write. The result page can save one synthetic vendor into the shared risk register when the visitor checks the box and records a disposition. Nginx's default upload limit is 1 MB, which is above the application's 256 KB cap.

`POST /api/v1/intake/assess` is open because `REQUIRE_AUTH` is false. Assess alone does not write. A body with `persist` true and a human disposition does write a synthetic row to the shared register. Do not send real vendor data. See `docs/bot-contract.md`.

The dashboard counts whatever synthetic rows are in the shared SQLite file. Those counts are observed for that file. They are not a baseline study, a monthly rate, or cash savings. The cost panel remains the illustrative formula in `app/data/cost_assumptions.json`. Self-reported handling minutes appear only when a saved decision includes them. Self-reported rework minutes appear on their own card only when a saved decision includes them. Self-reported manual touches appear on their own card only when a saved decision includes them. None of those figures is authenticated, and none is copied into that formula. A same-second intake and disposition is a 0-second elapsed span in that file, which is the clock record of the save. It is not those minutes.

## Snapshot restore drill

This drill has not been executed. Running it creates a second Lightsail instance and can add charges. Do it only with an account owner who accepts that cost.

1. In Lightsail for `us-east-2`, open instance `grc-assurance-engine-demo` and note the latest automatic snapshot. The template requests a daily snapshot at 08:00 UTC.
2. Create a new instance from that snapshot. Leave the production static IP and the DNS name on the original instance.
3. On the copy, check `systemctl is-active grc-assurance-engine`, request `http://127.0.0.1:8000/health`, and confirm a known synthetic row is still in `/var/lib/grc-assurance/grc_assurance.sqlite3`. After this revision is installed, the health JSON includes `"database": "reachable"` when the file can be read. A copy made from an older snapshot still has the health JSON from that snapshot.
4. Delete the copy when the check is finished. Record the date and the result somewhere outside this repository. Until that record exists, treat snapshots as untested recovery points.

## Operations and limitations

The instance and its daily snapshots incur AWS charges, so set an account budget alert. A snapshot is a recovery point for this one disk. It becomes a tested recovery path only after the drill above has been run and recorded. SQLite supports this single instance only; do not scale the design horizontally or use it for real vendor records. There is no login: anyone with the link can use the demo and add synthetic records to the shared risk register, so it must never hold real data. Nginx rate limits are whatever site file is installed on the host. The repository file limits `/try/` and `/api/` more tightly than other pages, and the live file matches that only after a person installs it. `deploy-app-revision.sh` does that only with `--update-nginx`. `/health` in this revision checks that the SQLite file can be read. That check is not a production readiness test. The demo is an illustrative portfolio prototype, not a production GRC service or certification tool.

## Local verification

Run `python -m pytest` from the repository root. The deploy-script tests source the shell helpers and do not open an SSH connection or a Lightsail session. The local `run.py` entry point stays bound to loopback and is not a production server.
