/**
 * Shown while a server component is still fetching.
 *
 * Every page here is a server component that awaits the API before it can render
 * anything, so without this the browser holds the *previous* screen — or a blank one on
 * first load — for the whole round trip, with nothing to say work is happening. On a
 * case page that is several sequential calls.
 *
 * A skeleton rather than a spinner, and deliberately so: it occupies the shape the real
 * content will take, so the page does not jump when it arrives. It carries no numbers
 * and no labels — a placeholder that showed "0 documents" would be a claim, and this
 * product has just spent a whole pass removing UI that asserted things it did not know.
 *
 * `aria-busy` with a live region, so a screen reader is told the page is loading rather
 * than being read an empty document.
 */
function Bar({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-paper-200 ${className}`} />;
}

export default function Loading() {
  return (
    <div className="min-h-screen bg-paper" aria-busy="true">
      <span role="status" className="sr-only">
        Loading
      </span>

      <div className="border-b border-paper-200 bg-white px-6 py-6 lg:px-10">
        <div className="mx-auto max-w-[88rem] space-y-3">
          <Bar className="h-3 w-24" />
          <Bar className="h-7 w-72" />
          <Bar className="h-3 w-48" />
        </div>
      </div>

      <div className="mx-auto max-w-[88rem] px-6 py-8 lg:px-10">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-4">
            <div className="surface space-y-3 px-5 py-5">
              <Bar className="h-4 w-40" />
              <Bar className="h-3 w-full" />
              <Bar className="h-3 w-5/6" />
              <Bar className="h-3 w-4/6" />
            </div>
            <div className="surface space-y-3 px-5 py-5">
              <Bar className="h-4 w-32" />
              <Bar className="h-3 w-full" />
              <Bar className="h-3 w-3/4" />
            </div>
          </div>
          <div className="space-y-4">
            <div className="surface space-y-3 px-5 py-5">
              <Bar className="h-3 w-28" />
              <Bar className="h-3 w-full" />
              <Bar className="h-3 w-2/3" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
