# 0018 — The web tier writes through form posts, not Server Actions

## Context
Slice 5b needs four writes from the browser: switch identity, commit a field, enter a
value, redact. Next's idiomatic mechanism is a Server Action, and that was the first
implementation.

It did not work here. Next guards Server Actions by comparing the request's `Origin`
header against the forwarded host and aborting when they disagree — a reasonable default
that fails in exactly the conditions this project has to survive. In the embedded browser
used to test it the origin arrived as `null` and every action was refused with *Invalid
Server Actions request*. A demo machine reached by IP rather than by name, or anything
proxied, can produce the same mismatch.

The cost of finding out late would be high: the failure appears only in a browser, not
in any test, and not until someone clicks.

## Decision
Writes are **plain HTML form posts to route handlers** under `web/app/actions/`. Each
handler forwards the session cookie to the API and relays the result as a 303.

Three things follow:

- **The pages work with JavaScript disabled entirely.** On a laptop in a hall, with
  somebody else's browser, that is worth more than a smoother transition.
- **Selection state lives in the URL** (`?version=…&field=…`) rather than in a client
  component, so the verification screen needs no hydration bundle and a highlighted
  field is a link that can be pasted.
- **Redirects carry a relative `Location`.** The framework's redirect helper builds an
  absolute URL from `request.url`, whose host is what the server resolved rather than
  what the browser typed; on this machine that turned `127.0.0.1` into `localhost` and
  the session cookie — set for the host that was asked for — was not sent back. RFC 7231
  permits a relative Location, and the app then behaves identically at `127.0.0.1`, at
  `localhost`, and at a LAN address a judge types.

## Consequences
- The CSRF protection Server Actions provided is replaced by the cookie's own
  `SameSite=Lax`, which browsers do not attach to a cross-site POST. That is the same
  control the API already relies on (threat SESS-03), stated in both route handlers.
- Every write costs a full page render. At this scale that is imperceptible and it makes
  the post-write state unambiguous.
- The handlers decide nothing. Authorization is re-checked at the API on every forwarded
  request, so a button rendered on a page grants nothing — press "verify" as a subject
  who may not and the field stays a draft.
- Failure reasons are mapped to a fixed set of codes here rather than relayed from the
  API, so this cannot become the place where a later route's free text reaches a screen
  (invariant 12).
