# AWS demo deployment

## Current state

The demo is open at `https://grc-assurance.davidoneal.dev`, with no login, when the host is up. A push to `main` does not install a commit. The pin is the SHA last written to `/etc/grc-assurance-revision` after local `/health` passes. This documentation change did not SSH to the instance, did not read that file, and did not dispatch GitHub Actions. Cloudflare proxies the hostname, so a public DNS lookup does not show the origin address.

### Checks recorded on October 14, 2026

On that date the demo was live and open, with no login. The password gate was removed on purpose: every record is synthetic, and the demo is shared by link. The DNS record was proxied through Cloudflare, a Configuration Rule set SSL to Full (strict) for this hostname only, and Nginx served HTTPS at the origin with a Cloudflare Origin CA certificate. These checks passed from outside the server on that date: `/health` returned the health JSON over HTTPS, `http://` requests redirected to `https://`, the public certificate was issued by Google Trust Services, and Nginx returned HTTP 429 once a single visitor exceeded the rate limit. This documentation change did not repeat those checks.

`infra/deploy-app-revision.sh` installs one full commit SHA on a host that already has the unit, the virtualenv, and the database. Merge `8dcfea2139ba86134697fe83fb4f64734e3155ce` was installed that way. Local `/health` passed, and `/etc/grc-assurance-revision` was written with that SHA. The process then exited non-zero: the EXIT trap expanded the function-local name `tarball` after `main` returned, and `set -u` reported it as an unbound variable. The `sqlite3` CLI was not on the host until it was installed for that run. curl and python3 were already there. A later commit keeps the tarball path in a global for that trap, and it adds the `sqlite3` package to the bootstrap install line. Committing that fix did not install it and did not SSH to the instance. The October 14 checks describe the host as it was then.

### Owner-recorded notes after that install

These notes are the owner's record. This documentation change did not repeat them and did not SSH.

- On 2026-10-27 a snapshot restore drill was run. The recorded result is under Snapshot restore drill. The copy's pin was `257a67e4f2e2245b6f15e9775fa6181d78f93e85`. The production static IP was left at `77.112.210.29`, and the copy was deleted. This file does not re-check that the origin is still that address.
- The owner reports that the systemd unit was later switched to the `grc-assurance` account by re-running `infra/lightsail-bootstrap.sh`. The bootstrap in this repository creates that account when it is missing and sets `User=` to it. The app-revision script does not change `User=`. The live account was not re-checked for this note.
- The owner states that on 2026-10-28 the public demo was serving `da9329c2aed979fcf6465392b9b4393fa03e7421` (observed metrics definition 8). That is the owner's statement of the deployed commit on that date. It is not a pin read from the host during this documentation change.

### Not re-checked from this repository

- Whether the Nginx file on the host matches `infra/nginx-site.conf`. The app-revision script copies that file only with `--update-nginx`.
- Whether GitHub Actions has completed a deploy. The workflow still cannot SSH until the secrets exist and the administrator `/32` allows the runner.
- Whether a snapshot newer than the 2026-10-27 drill would restore. That drill covers the snapshot used that day.
- The October 14 certificate, redirect, and HTTP 429 checks.

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
- Backs up the live SQLite file with the `sqlite3` `.backup` command, which uses SQLite's online backup API, before it changes the app tree. The CLI has to be on `PATH`. The script does not install OS packages and does not skip the backup when `sqlite3` is missing. Each backup is a new file under `/var/lib/grc-assurance/backups/`. The script does not delete old backups, and it does not delete `/var/lib/grc-assurance/` or `grc_assurance.sqlite3`. Those files are on the same disk as the demo. They are not a substitute for the Lightsail snapshot. One restore drill is recorded below. A later snapshot stays untested until another drill is recorded.
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

The log is `/var/log/grc-assurance-deploy.log`. A second deploy waits on `/var/lock/grc-assurance-deploy.lock`. The log and the lock are local files. They are not an immutable audit trail. The online backup uses the `sqlite3` CLI. `lightsail-bootstrap.sh` installs that package with the other first-install packages. A host built before that package was on the install line needs `sudo apt-get install -y sqlite3` once. The app-revision script still stops, before it changes the app tree, if the CLI is not installed. It does not skip the backup. If the health check fails, the log names the backup path. Fix the unit or the env file and re-run the same SHA, or re-run the previous SHA. A code rollback does not reverse schema changes already applied to the SQLite file. Migrations in this application add columns and rebuild the decisions table in place; they do not drop saved rows. The workflow-event chain migration adds `prev_hash`, `hash`, and `chain_origin` when those columns are missing, hashes rows that already exist once, and marks those rows `chained_after_the_fact`. A later startup does not rehash them. Rolling back to a revision that inserts events without those hashes leaves the new rows unhashed, and the one-time backfill does not fill them in again. The chain check on a revision that has the check then reports the first unhashed row. A non-zero exit after the pin file is written can be the EXIT trap rather than a failed health check. The trap now stores the tarball path outside `main`, so a finished deploy can return 0.

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

The Lightsail firewall allows SSH only from the administrator `/32` in the CloudFormation `AdminCidr` parameter. A GitHub-hosted runner uses a different address. This workflow does not change that rule, and it does not open port 22. Until SSH from the runner is allowed, a dispatch that has the secrets still fails at the SSH step. The host command above does not have that limit, because it runs inside a session that is already allowed. No deploy was run from Actions for the change that added this workflow. This documentation change did not dispatch it, and it does not record whether a later dispatch succeeded.

## Known gaps

### Host state after the `8dcfea2139ba86134697fe83fb4f64734e3155ce` dogfood

This table is the state reported for that install. It is not a description of the host after the owner-recorded notes above. That install used the app-revision script. It does not rewrite the systemd unit, and it does not reload Nginx unless `--update-nginx` is set. The reported run did not include an Nginx change. The EXIT-trap follow-up was not part of that install. Committing that follow-up did not SSH to the instance, reload Nginx, or update the CloudFormation stack.

| Gap | In the repository | On the live host after that dogfood |
| --- | --- | --- |
| Installed revision | App updates install one full SHA and record it in `/etc/grc-assurance-revision` only after local `/health` passes. | The pin file was written with `8dcfea2139ba86134697fe83fb4f64734e3155ce`. Later pins are not listed in this table. |
| Stale app files | A deploy deletes app-tree files that are not in the pinned tarball. It keeps `.venv` and `instance/`. The SQLite path stays outside the app tree. | That run replaced the app tree and kept `.venv` and `instance/`. |
| Service account | The bootstrap unit runs as `grc-assurance`, created on the host when missing. The `ubuntu` account remains for SSH. The app-revision script does not change `User=`. | After that run, the unit still used whatever account it had before the run. A later bootstrap re-run is an owner report, not a row in this table. |
| Database readiness | `GET /health` opens the configured SQLite file read-only. Reachable is HTTP 200 and `"database": "reachable"`. Unreachable is HTTP 503 and `"database": "unreachable"`. The body has no path and no driver message. | Local `/health` passed, which requires `"status":"ok"` and `"database":"reachable"`. |
| Deploy exit status | The EXIT trap keeps the downloaded tarball path in `CLEANUP_TAR_FILE`, which is not a function local, so a finished `main` can return 0 under `set -u`. | That run exited non-zero after the pin was written, with `tarball: unbound variable`. |
| `sqlite3` CLI | The bootstrap installs the `sqlite3` package. The app-revision script stops if the CLI is missing and does not skip the backup. | The package was missing. It was installed on the host before the health check passed. That follow-up did not re-run the bootstrap. |
| `/api/` rate limit | `infra/nginx-site.conf` limits `/api/` to 20 requests a minute per visitor (burst 10) and 5 requests a second across visitors (burst 20), the same budget as `/try/`. Other pages stay at 120 requests a minute per visitor. | The reported run did not include `--update-nginx`. The live site file changes only when that flag is used or the file is copied by hand. |

A database result of `reachable` means the file opened read-only and its catalog could be read. It does not validate schema completeness, integrity, disk space, or backups. It does not make the demo production-ready.

### Still open

One snapshot restore drill is recorded below, for the snapshot used on 2026-10-27. A later snapshot is untested until another drill is recorded. This documentation change did not run a drill.

There is no login. `REQUIRE_AUTH` stays false on purpose for the open demo. Anyone with the link can use the demo and add synthetic records to the shared risk register. The register must never hold real data.

SQLite supports this single instance only. There is no second host, no replica, and no highly available database.

The app-revision script and the manual workflow are the update path for a host that is already bootstrapped. The workflow does not run on push. It cannot SSH until the secrets in Updating and rolling back exist, and the instance SSH rule is still the administrator `/32`. Nginx changes only when `--update-nginx` is passed. The bootstrap remains the first-install path and the path that rewrites the systemd unit.

The owner reports a later bootstrap re-run that set the `grc-assurance` account. This file does not re-check `User=`. A dedicated account, the read-only health check, and the tighter `/api/` limit are ordinary host hygiene. They are not a production hardening claim.

### Unchanged product behavior

File import reads an uploaded CSV, `.xlsx`, or simulated ServiceNow JSON/CSV file. It does not connect to ServiceNow. Preview and confirm do not write. The result page can save one synthetic vendor into the shared risk register when the visitor checks the box and records a disposition. Nginx's default upload limit is 1 MB, which is above the application's 256 KB cap.

`POST /api/v1/intake/assess` is open because `REQUIRE_AUTH` is false. Assess alone does not write. A body with `persist` true and a human disposition does write a synthetic row to the shared register. Do not send real vendor data. See `docs/bot-contract.md`.

The dashboard counts whatever synthetic rows are in the shared SQLite file. Those counts are observed for that file. They are not a baseline study, and they are not cash savings. The monthly assessment rate is a count of current decisions in a covered 30-day window. A shorter history on that file says Not measured. The cost panel remains the illustrative formula in `app/data/cost_assumptions.json`. Self-reported handling minutes appear only when a saved decision includes them. Self-reported rework minutes appear on their own card only when a saved decision includes them. Self-reported manual touches appear on their own card only when a saved decision includes them. Self-reported handoffs appear on their own card only when a saved decision includes them. None of those four figures is authenticated effort, and none is copied into that formula. Authenticated effort is a separate card for optional minutes a signed-in reviewer entered. Cash savings are a separate card for optional whole dollars a signed-in reviewer entered. The open demo leaves the password gate off, so those two cards stay Not measured unless a signed-in disposition stored a number. Neither is copied into the cost formula. Avoided-incident value is a separate modeled-assumption card. The shipped assumptions leave both inputs null, so that card says Not measured on the open demo. It is not cash savings and it is not copied into the cost formula. A same-second intake and disposition is a 0-second elapsed span in that file, which is the clock record of the save. It is not those minutes.

## Snapshot restore drill

Running the drill creates a second Lightsail instance and can add charges. Do it only with an account owner who accepts that cost.

### Recorded result, 2026-10-27

The owner recorded one drill outside this repository, at `C:\Users\oneal\grc-assurance-snapshot-restore-drill-2026-10-27.txt` on the owner's machine. This documentation change did not repeat the drill and did not copy that file into git.

| Check | Recorded result |
| --- | --- |
| Source instance | `grc-assurance-engine-demo` |
| Temporary copy | `grc-assurance-restore-drill-202610271020`, created from a snapshot of that instance, then deleted |
| Unit on the copy | `systemctl is-active grc-assurance-engine` reported active |
| Health on the copy | `http://127.0.0.1:8000/health` reported the database reachable |
| Data on the copy | A synthetic row in `risks` was still present in `/var/lib/grc-assurance/grc_assurance.sqlite3` |
| Pin on the copy | `257a67e4f2e2245b6f15e9775fa6181d78f93e85` |
| Production address | Left on the original instance at `77.112.210.29`. The DNS name was not moved. |

That record shows the snapshot used that day could boot, serve `/health` with the database reachable, and keep a synthetic row. It does not show that a later snapshot would restore, that the current disk matches that snapshot, or that the demo is production-ready. The address in the table is the address the drill left in place. This change did not re-resolve it.

### Procedure for a later drill

1. In Lightsail for `us-east-2`, open instance `grc-assurance-engine-demo` and note the latest automatic snapshot. The template requests a daily snapshot at 08:00 UTC.
2. Create a new instance from that snapshot. Leave the production static IP and the DNS name on the original instance.
3. On the copy, check `systemctl is-active grc-assurance-engine`, request `http://127.0.0.1:8000/health`, and confirm a known synthetic row is still in `/var/lib/grc-assurance/grc_assurance.sqlite3`. The health JSON includes `"database": "reachable"` when the file can be read. A copy made from an older snapshot still has the health JSON from that snapshot.
4. Delete the copy when the check is finished. Record the date and the result somewhere outside this repository. Until that later record exists, treat snapshots taken after 2026-10-27 as untested recovery points.

## Operations and limitations

The instance and its daily snapshots incur AWS charges, so set an account budget alert. A snapshot is a recovery point for this one disk. The 2026-10-27 drill is one recorded recovery of the snapshot used that day. A later snapshot is untested until another drill is recorded. SQLite supports this single instance only; do not scale the design horizontally or use it for real vendor records. There is no login: anyone with the link can use the demo and add synthetic records to the shared risk register, so it must never hold real data. Nginx rate limits are whatever site file is installed on the host. The repository file limits `/try/` and `/api/` more tightly than other pages, and the live file matches that only after a person installs it. `deploy-app-revision.sh` does that only with `--update-nginx`. `/health` checks that the SQLite file can be read. That check is not a production readiness test. The demo is an illustrative portfolio prototype, not a production GRC service or certification tool.

## Workflow event chain

When a revision that includes the hash chain starts, startup adds `prev_hash`, `hash`, and `chain_origin` to `workflow_events` if those columns are missing. Rows already in the table are hashed once, in `event_id` order, and marked `chained_after_the_fact`. That mark means the hash was added later. It does not mean the original write was covered at the time. Later events are hashed when they are inserted (`chain_origin` `appended`). The methods page and the dashboard show the result of `verify_event_chain()`. The label is tamper-evident, not tamper-proof.

A person who can write the SQLite file can change a row and recompute every later hash, or replace the table and the stored tip. The check then reports intact. The chain is not immutable storage, a production audit log, or a certification. It does not feed observed metrics and it does not change `calculate_cost()`. Deleting every event and the tip leaves an empty log, which also reports intact.

This documentation change did not install a revision and did not open the live database. The live file is chained only after a revision that contains this migration is started on the host.

## Local verification

Run `python -m pytest` from the repository root. The deploy-script tests source the shell helpers and do not open an SSH connection or a Lightsail session. The local `run.py` entry point stays bound to loopback and is not a production server.
