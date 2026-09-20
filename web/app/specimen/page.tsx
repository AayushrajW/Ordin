/**
 * The specimen identity switcher, and the front panel beside it.
 *
 * Lives at /specimen rather than at / because the product now has a real login. It is
 * kept because the demo depends on it: "same URL, three identities" is the clearest
 * thing this system can show anyone, and logging out and back in three times destroys
 * that.
 *
 * It checks no credential, so `api/session.py` refuses its endpoints entirely unless
 * `ORDIN_ENV=dev`. This page is therefore inert in a deployment: the list comes back
 * empty and the switch would 404. The route guard here is the courtesy; the API's
 * refusal is the control.
 */
import { redirect } from "next/navigation";

import { IconArrowRight, IconChain, IconEye, IconLock, IconRedact, IconShield, Seal } from "../components/icons";
import { initials } from "../components/Shell";
import { currentSubject, get, type DemoSubject } from "../lib/api";

export const dynamic = "force-dynamic";

const PROMISES = [
  { icon: <IconShield className="h-4 w-4" />, title: "Authorization inside every query",
    body: "Seven dimensions, evaluated in the database. A case you may not open is not in the list, the count, the search or the autocomplete." },
  { icon: <IconRedact className="h-4 w-4" />, title: "Redaction that destroys, not covers",
    body: "Every mention of a protected identity is found and burned out of the page — including the ones in the narrative." },
  { icon: <IconChain className="h-4 w-4" />, title: "A hash-chained record of custody",
    body: "Every commit, upload and view is an append-only audit row that commits to the one before it." },
  { icon: <IconEye className="h-4 w-4" />, title: "Nothing leaves this machine",
    body: "No cloud, no model, no telemetry. OCR, extraction and verification run offline." },
];


async function Switcher() {
  const directory = await get<{ subjects: DemoSubject[] }>("/demo/subjects");
  const subjects = directory?.subjects ?? [];
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <section className="relative overflow-hidden bg-ink-900 px-8 py-12 text-ink-100 lg:px-14 lg:py-16">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(90%_70%_at_10%_0%,rgba(200,156,75,0.16),transparent_60%),radial-gradient(70%_60%_at_100%_100%,rgba(68,89,214,0.18),transparent_60%)]" />
        <div className="relative flex h-full max-w-xl flex-col">
          <div className="flex items-center gap-3">
            <Seal className="h-11 w-11" />
            <div>
              <p className="font-serif text-2xl leading-none text-white">Ordin</p>
              <p className="mt-1 text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300/80">
                Evidence registry
              </p>
            </div>
          </div>

          <h1 className="mt-14 font-serif text-[2.6rem] leading-[1.08] tracking-tight text-white lg:mt-20">
            The case record,
            <br />
            <span className="text-brass-300">not the document store.</span>
          </h1>
          <p className="mt-5 max-w-md text-[0.95rem] leading-relaxed text-ink-300">
            Case-centric evidence intelligence for investigation and prosecution. A document
            here exists as proof that a step in a case lawfully happened — and every screen
            shows only what the person looking is entitled to see.
          </p>

          <ul className="mt-10 grid gap-5 sm:grid-cols-2">
            {PROMISES.map((p) => (
              <li key={p.title} className="animate-rise">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-ink-800 text-brass-300 ring-1 ring-ink-700">
                  {p.icon}
                </span>
                <p className="mt-3 text-[0.8125rem] font-semibold text-white">{p.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-ink-400">{p.body}</p>
              </li>
            ))}
          </ul>

          <p className="mt-auto pt-12 text-[0.6875rem] text-ink-500">
            SIH 2026 · Problem Statement 26190 · Team Valora · specimen environment — every
            record is synthetic.
          </p>
        </div>
      </section>

      <section className="flex items-center px-6 py-12 lg:px-14">
        <div className="mx-auto w-full max-w-md">
          <p className="eyebrow text-brass-600">Specimen switcher — not a login</p>
          <h2 className="mt-2 font-serif text-3xl tracking-tight text-ink-900">Choose who you are</h2>
          <p className="mt-2 text-sm leading-relaxed text-ink-500">
            No credential is checked. The server signs the identity you pick, and every
            decision after that — designation, grant, clearance, purpose, expiry — is made
            from that token on the server, never from anything this page sends.
          </p>

          <div className="mt-8 space-y-2.5">
            {subjects.map((s, i) => (
              <form key={s.user_id} method="post" action="/actions/session" style={{ animationDelay: `${i * 60}ms` }} className="animate-rise">
                <input type="hidden" name="user_id" value={s.user_id} />
                <input type="hidden" name="next" value="/" />
                <button
                  type="submit"
                  aria-label={`${s.display_name}, ${s.title}`}
                  className="surface group flex w-full items-center gap-4 px-4 py-3.5 text-left transition hover:-translate-y-px hover:border-brass-300 hover:shadow-lift"
                >
                  <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-gradient-to-br from-ink-700 to-ink-900 text-sm font-semibold text-white ring-2 ring-paper-200">
                    {initials(s.display_name)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[0.9rem] font-semibold text-ink-900">{s.display_name}</span>
                    <span className="block text-xs text-ink-500">{s.title}</span>
                  </span>
                  <IconArrowRight className="h-4 w-4 text-ink-300 transition group-hover:translate-x-0.5 group-hover:text-brass-500" />
                </button>
              </form>
            ))}
          </div>
          {subjects.length === 0 && (
            <p className="mt-8 rounded-xl border border-danger-100 bg-danger-50 px-4 py-3 text-sm text-danger-700">
              The API is not answering. Start it with <span className="kbd">python tasks.py up</span>.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}


export default async function SpecimenPage() {
  if (process.env.ORDIN_ENV !== "dev") redirect("/login");
  const subject = await currentSubject();
  if (subject) redirect("/");
  return <Switcher />;
}
