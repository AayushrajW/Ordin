/**
 * An unknown URL.
 *
 * **Worded so it cannot be read as an authorization answer.** Everywhere else in this
 * product, "not available to you" and "no such thing" are deliberately the same
 * response: a 403 on a case you may not open confirms the case exists, which is an
 * existence oracle over guessable ids (threat INS-04). A 404 page that said "this case
 * does not exist" would undo that from the other side — a reader could compare this
 * screen against the in-app refusal and learn which of the two had happened.
 *
 * So this page talks about the address, never about a record.
 */
export default function NotFound() {
  return (
    <div className="grid min-h-screen place-items-center bg-paper px-6">
      <div className="surface mx-auto w-full max-w-lg px-6 py-8 text-center">
        <p className="eyebrow">Unknown address</p>
        <h1 className="section-title mt-2">There is nothing at this address</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-500">
          The link may be mistyped or out of date. This says nothing about whether any
          particular record exists — screens inside Ordin answer that, and they answer it
          the same way whether a record is missing or simply not yours.
        </p>
        <div className="mt-6">
          <a href="/" className="btn-primary">
            Back to case files
          </a>
        </div>
      </div>
    </div>
  );
}
