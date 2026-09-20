/**
 * Values that must agree with the API.
 *
 * `MIN_PASSWORD` mirrors `infra/passwords.MIN_LENGTH`. The browser check is a courtesy
 * so a person is told before the round trip; the one that matters is the server's,
 * which runs whatever the form sends.
 */
export const MIN_PASSWORD = 12;
