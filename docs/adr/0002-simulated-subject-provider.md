# 0002 — Authentication is a declared stub, resolved server-side

## Context
`BOOTSTRAP.md` slices 1-12 contain no authentication, session or identity slice. The
authorization model evaluates seven dimensions over a subject, and nothing establishes
that subject. Every control in slice 3 is therefore enforced against a self-asserted
principal.

Slice 7 ("one document, three roles, one URL") actively pressures toward the cheapest
implementation: a client-side role selector sending a request parameter or header the API
trusts. That would silently invalidate slices 3, 7 and 8 at once — Sentinel's
unauthorized-access scenario would pass against a forgeable identity.

A real identity provider does not fit in a 30-hour budget.

## Decision
Ship `SimulatedSubjectProvider`: `maturity: mvp`, with `production_adapter` naming a real
IdP. The subject is resolved **server-side from a signed session**, never from a request
parameter or header, and the slice 7 role-switch reads from that session.

Per the honesty rules it is never named as an auth service, and the gap is written up as
accepted risk AR-1 in `docs/THREAT-MODEL.md` rather than left implicit.

## Consequences
- The seven-dimension model becomes demonstrable rather than decorative.
- Session security itself is not built: no rate limiting, lockout, or enumeration
  protection (AR-9). Binding published ports to localhost is the cheap partial mitigation.
- Seeded credentials ship in a public repo (EXT-03); nothing forces demo-time rotation.
- A session-signing secret written as a compose or settings default is invisible to the
  guard hook — it is neither an environment file nor a private key.
