# 0024 — Real authentication, and why it barely touched the authorization model

## Context
ADR 0002 chose a `SimulatedSubjectProvider`: a signed session token issued for any
seeded identity, with no credential, named so nobody could mistake it for an identity
provider. Correct for a hackathon and indefensible in a deployment, which the builder
asked for on 2026-09-20.

## Decision
`api/auth.py` verifies a password and issues **the same token the switcher issued**.

That is the whole change at the identity boundary. `api/deps.require_subject` already
re-resolved the seven dimensions from the database on every request and trusted the token
for nothing but *who*. So the policy evaluator, the SQL filter in `infra/authz_sql.py`,
the disclosure class and all nineteen Sentinel scenarios are untouched, and no
authorization test needed changing. The system was built so that identity is resolved
server-side from a signature; swapping what produces the signature is a boundary change.

**Argon2id via argon2-cffi**, at OWASP's minimum parameters (19 MiB, t=2, p=1) rather
than the library's 64 MiB default, because the api container is capped at 256 MiB and a
handful of simultaneous logins at the default would reach the OOM killer from an
unauthenticated endpoint. Stated in `infra/passwords.py` rather than discovered later.

**Signup creates an account with no post.** No post means no organization, no
jurisdiction and no clearance, which means `load_subject` returns None and every
authorized query is empty. This is enforced by the shape of the data, not by a check
somebody has to remember: the join to `post` simply yields no row. An administrator
places the account afterwards.

**Administration is a property of the post** (`post.is_administrative`), not of the
person. It is an office, which is the same distinction the model already draws between
identity and post, and it keeps invariant 3 intact — the policy evaluator reads it
through a predicate, so administrative access is decided by versioned policy data and
logs the policy ID that decided it. `app_user.is_admin` would have been the forbidden
hand-rolled check with a column behind it.

**The specimen switcher now 404s unless `ORDIN_ENV=dev`.** Hiding it from the UI is not
a control; this repository is public. It is kept rather than deleted because
"same URL, three identities" is the clearest thing this system can show anyone.

## Consequences
- Failures are uniform. A wrong password, an unknown address, a duplicate signup and a
  malformed one all return identical responses, because the differences answer *does
  this person work here* to a caller who has proved nothing. Tests assert the responses
  are byte-identical rather than merely both failures.
- Lockout is counted **on the account row**, not only in the sliding window, because
  `api/security.py` says of itself that it is per process and resets on restart.
- A signed-in but unplaced account needs somewhere to land, or a successful login
  bounces to the login form and reads as a broken login. `/awaiting-placement` says what
  happened and why.
- `app_user.post_id` became nullable. The downgrade deletes unplaced accounts, because
  they cannot satisfy the old NOT NULL.
- Argon2 verification is deliberately performed against a decoy hash when no account
  matches, so absence is not detectable by clock.
