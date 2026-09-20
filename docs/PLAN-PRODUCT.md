# PLAN — from demo to deployable product

Written 2026-09-20, after the builder's direction: *"I want the product that could be
published or deployed. This is just for show — I cannot upload files or images, cannot
search the database, cannot login/signup."*

Two of those three were accurate. This plan closes all of them.

## What was actually true

| claim | finding |
|---|---|
| cannot upload files or images | **Present but unusable.** The multipart route, the API and the worker path all worked and were covered by tests; the control was styled `file:hidden`, which hides `::file-selector-button`, so there was no visible way to open the picker. Fixed first, in `web/app/cases/[caseId]/page.tsx`. |
| cannot search the database | **Accurate in effect.** `GET /cases/search` and an authorization-joined `GET /cases/parties/suggest` exist in the API; there is no search UI anywhere, and no full-text search over document content. |
| cannot login/signup | **Accurate and deliberate.** ADR 0002: a signed specimen switcher, named "not an identity provider". Defensible for a hackathon, not for a deployment. |

## The decisions taken

**Accounts plus administration**, and **both** deployment targets — on-premise compose
and a cloud host — chosen by the builder on 2026-09-20.

## The load-bearing design decision

**Authentication changes only how a caller proves which identity they are. It does not
touch the authorization model at all.**

`SimulatedSubjectProvider` already mints a server-signed session token carrying a
`user_id`, and every access decision downstream is made from that token against the
seven dimensions. Real login replaces *one button click* with *a verified password* and
then issues the same token. The policy evaluator, the SQL filter, the disclosure class
and every Sentinel scenario are untouched.

That is the whole reason this is a tractable change rather than a rewrite, and it is
worth saying out loud in the deck: the system was built so that identity is resolved
server-side from a signature, so swapping the thing that produces the signature is a
boundary change.

## Slices

### P1 — the upload control is usable ✅ done
Native control styled rather than hidden, so the picker opens and the browser's own
filename display confirms the choice, with no client-side JavaScript.

### P2 — real accounts
- Migration `0009_accounts`: `app_user` gains `email` (unique, citext), `password_hash`,
  `is_active`, `created_at`, `last_login_at`, `failed_attempts`, `locked_until`.
- `PasswordAuthenticator` verifies and issues the existing signed token.
  `SimulatedSubjectProvider` survives **only** when `ORDIN_ENV=dev`, so the specimen
  switcher cannot exist in production. It keeps its honest name.
- `/login`, `/logout`, `/signup` pages and routes.
- **Signup creates an inactive account with no organization, no jurisdiction and no
  clearance.** Nobody self-serves their way into a case. An administrator activates and
  places them. This is not friction for its own sake: an account that could assign its
  own organization would defeat the entire authorization model.
- Rate limiting on login (the sliding window in `api/security.py` already exists).
- Generic failure text: "those credentials do not match", never "no such user", which
  is an account-enumeration oracle.

### P3 — administration
Users, case assignments, grants, clearance. Each action appends an audit row.

**Administrative capability is a policy decision, never `if user.is_admin`.** CLAUDE.md
invariant 3 forbids the hand-rolled check by name. A new policy `ordin.admin` and a
predicate carry it, unit-tested with no app running, and every decision logs the policy
ID that made it — exactly as case access already does.

### P4 — search
- A search box that reaches cases, parties and document content.
- Postgres full-text over `ocr_text`, the retrieval path CLAUDE.md already decided.
- **The authorization predicate goes inside the query** (invariant 1), and snippets are
  gated by disclosure class: a grantee must never receive a snippet drawn from an
  original, because the original's derived text is original content in a different shape
  (threat VIC-01, `infra/disclosure.py`). This is the single most dangerous slice in the
  plan for that reason, and it gets its own Sentinel scenario.

### P5 — deployment
- `docker-compose.prod.yml`: no bind mounts, no dev secrets, restart policies,
  healthchecks, migrations on boot, a reverse proxy terminating TLS.
- Secrets from the environment, generated not defaulted; the app refuses to start in
  production with a development secret.
- A cloud target for a submittable URL, with its constraints stated honestly: free tiers
  sleep, and Tesseract plus PyMuPDF make a large image.
- Backup and restore of the Postgres volume, written down and actually run once.

## Invariants this plan could plausibly violate

1. **Invariant 3 — the likeliest.** Administration screens are where `if user.is_admin`
   gets written. It goes through the policy evaluator or it does not ship.
2. **Invariant 1 — search.** A search that filters after ranking leaks through result
   counts and snippets. The predicate joins inside the query.
3. **Invariant 12 — a password must never reach a log.** Not on failure, not in a
   validation error, not in a traceback.
4. **Never invent cryptography.** argon2-cffi (MIT) does the hashing. The session
   signature stays HMAC as it already is.
5. **Invariant 2.** An inactive, locked or unplaced account denies. A signup that left an
   account usable before an administrator placed it would be the whole model defeated.

## Dependency asked for and approved

| package | purpose | licence | cost | production path |
|---|---|---|---|---|
| argon2-cffi | password hashing | MIT | ~1 MB, negligible RAM | unchanged; it is the production answer |

Approved by the builder on 2026-09-20 as part of choosing "accounts + admin user
management".

## Order

P1 done. Then P2, P3, P4, P5 — auth before administration because administration has
nothing to administer without accounts, and search last among the features because it is
the one most likely to leak and deserves the most attention.
