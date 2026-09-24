/**
 * Administration: placing accounts, designating officers, issuing grants.
 *
 * **This page renders and enforces nothing.** Every list it shows arrives already
 * decided by `require_admin` at the API, which is a policy decision made by
 * `ordin.admin`. A non-administrator reaching this URL gets `null` from every fetch and
 * sees the "not available" panel — the same thing a URL for something that does not
 * exist would produce, because the API answers 404 rather than 403.
 *
 * The three things it makes visible, in the order an administrator needs them:
 *
 *  1. **Accounts awaiting placement** — people who signed up and can do nothing yet.
 *     This is the queue, so it is first, and it says so when it is empty.
 *  2. **Every account**, with what it holds.
 *  3. **Who currently has access to what** — the question AR-14 recorded as
 *     unanswerable.
 */
import { redirect } from "next/navigation";

import Shell, { PageHeader, initials } from "../components/Shell";
import { IconArrowRight, IconLock, IconShield } from "../components/icons";
import { Empty, Notice, relative } from "../components/ui";
import {
  currentSubject,
  get,
  type AdminAccount,
  type AdminCase,
  type AdminPost,
  type CurrentAccess,
} from "../lib/api";

export const dynamic = "force-dynamic";

const MESSAGES: Record<string, string> = {
  refused: "That was refused. Nothing changed.",
  unknown: "Unrecognised action. Nothing changed.",
};

const DONE: Record<string, string> = {
  place: "Account placed.",
  suspend: "Account suspended. It stops working on its next request, not at session end.",
  assign: "Designated. That case is now open to them.",
  unassign: "Designation ended. The row is kept, with its validity window closed.",
  grant: "Grant issued. It expires by itself.",
  revoke: "Grant revoked. Effective on the next request; delivered bytes are beyond reach.",
};

export default async function AdminPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; done?: string }>;
}) {
  const { error, done } = await searchParams;
  const subject = await currentSubject();
  if (!subject) redirect("/login");

  const [accounts, posts, cases, access] = await Promise.all([
    get<AdminAccount[]>("/admin/users"),
    get<AdminPost[]>("/admin/posts"),
    get<AdminCase[]>("/admin/cases"),
    get<CurrentAccess>("/admin/access"),
  ]);

  if (accounts === null) {
    return (
      <Shell subject={subject} returnTo="/admin" active="admin">
        <PageHeader crumbs={[{ label: "Administration" }]} title="Not available" />
        <div className="mx-auto max-w-[88rem] px-6 py-8 lg:px-10">
          <Empty title="There is no administration here for this identity">
            It does not exist, or you may not reach it — deliberately indistinguishable.
          </Empty>
        </div>
      </Shell>
    );
  }

  const waiting = accounts.filter((a) => !a.placed);
  const placed = accounts.filter((a) => a.placed);
  const ordinaryPosts = (posts ?? []).filter((p) => !p.is_administrative);

  return (
    <Shell
      subject={subject}
      returnTo="/admin"
      active="admin"
      voice={{
        briefing:
          `Administration. ${accounts.length} accounts, ${waiting.length} awaiting placement. ` +
          `${access?.designations.length ?? 0} live designations and ` +
          `${access?.grants.length ?? 0} live grants. This screen reads no case content.`,
      }}
    >
      <PageHeader
        crumbs={[{ label: "Administration" }]}
        title="Administration"
        hindi="प्रशासन"
        meta="Placing accounts, designating officers and issuing grants. Nothing here reads a case: an administrator decides who may look, and does not look."
      />

      <div className="mx-auto max-w-[88rem] px-6 py-8 lg:px-10">
      {done && DONE[done] && <Notice tone="verified" title={DONE[done]} />}
      {error && <Notice tone="danger" title={MESSAGES[error] ?? MESSAGES.refused} />}

      {/* 1. The queue. */}
      <section className="mt-6">
        <div className="flex items-baseline justify-between">
          <h2 className="font-serif text-xl tracking-tight text-ink-900">Awaiting placement</h2>
          <span className="text-xs text-ink-500">
            {waiting.length === 0 ? "nobody" : `${waiting.length} waiting`}
          </span>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-ink-500">
          These accounts exist and hold no post, so they have no organization, no
          jurisdiction and no clearance, and can open nothing at all. Placing one is what
          makes it usable — it is still not access to any case.
        </p>

        {waiting.length === 0 ? (
          <div className="surface-quiet mt-4 px-5 py-6 text-sm text-ink-500">
            Nobody is waiting. Accounts appear here when somebody requests one at{" "}
            <span className="kbd">/signup</span>.
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {waiting.map((a) => (
              <form
                key={a.user_id}
                method="post"
                action="/actions/admin"
                className="surface flex flex-wrap items-end gap-4 px-5 py-4"
              >
                <input type="hidden" name="action" value="place" />
                <input type="hidden" name="user_id" value={a.user_id} />
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-gradient-to-br from-ink-700 to-ink-900 text-xs font-semibold text-white ring-2 ring-paper-200">
                  {initials(a.display_name)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[0.9rem] font-semibold text-ink-900">{a.display_name}</p>
                  <p className="truncate text-xs text-ink-500">{a.email}</p>
                </div>
                <label className="block">
                  <span className="mb-1 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
                    Post
                  </span>
                  <select name="post_id" required className="field min-w-[15rem] text-xs">
                    {ordinaryPosts.map((p) => (
                      <option key={p.post_id} value={p.post_id}>
                        {p.title} — {p.organization}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
                    Clearance
                  </span>
                  <select name="clearance_level" className="field text-xs">
                    <option value="1">1 — ordinary</option>
                    <option value="2">2 — elevated</option>
                    <option value="3">3 — sealed records</option>
                  </select>
                </label>
                <button type="submit" className="btn-primary">
                  Place <IconArrowRight className="h-4 w-4" />
                </button>
              </form>
            ))}
          </div>
        )}
      </section>

      {/* 2. Everyone. */}
      <section className="mt-10">
        <h2 className="font-serif text-xl tracking-tight text-ink-900">Accounts</h2>
        <div className="surface mt-4 overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-paper-200 bg-paper-100 text-[0.65rem] uppercase tracking-[0.12em] text-ink-400">
              <tr>
                <th className="px-4 py-2.5 font-semibold">Person</th>
                <th className="px-4 py-2.5 font-semibold">Post</th>
                <th className="px-4 py-2.5 font-semibold">Clearance</th>
                <th className="px-4 py-2.5 font-semibold">Live access</th>
                <th className="px-4 py-2.5 font-semibold">Last seen</th>
                <th className="px-4 py-2.5 font-semibold" />
              </tr>
            </thead>
            <tbody className="divide-y divide-paper-200">
              {placed.map((a) => (
                <tr key={a.user_id} className={a.is_active ? "" : "opacity-55"}>
                  <td className="px-4 py-3">
                    <p className="font-semibold text-ink-900">{a.display_name}</p>
                    <p className="text-xs text-ink-500">{a.email ?? "specimen identity"}</p>
                  </td>
                  <td className="px-4 py-3 text-xs text-ink-600">
                    {a.post_title}
                    <span className="block text-ink-400">{a.organization}</span>
                    {a.is_administrative && (
                      <span className="chip-brass mt-1 inline-flex">
                        <IconShield className="h-3 w-3" /> administrative
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-ink-600">{a.clearance_level}</td>
                  <td className="px-4 py-3 text-xs text-ink-600">
                    {(() => {
                      // Matched on user_id. Matching on display_name merged two officers who
                      // share a name and showed each of them the other's access.
                      const d = (access?.designations ?? []).filter((x) => x.user_id === a.user_id).length;
                      const g = (access?.grants ?? []).filter((x) => x.user_id === a.user_id).length;
                      if (!d && !g) return <span className="text-ink-400">none in force</span>;
                      return (
                        <span>
                          {d ? <span className="block">{d} designation{d === 1 ? "" : "s"}</span> : null}
                          {g ? <span className="block">{g} grant{g === 1 ? "" : "s"}</span> : null}
                        </span>
                      );
                    })()}
                  </td>
                  <td className="px-4 py-3 text-xs text-ink-500">
                    {a.last_login_at ? relative(a.last_login_at) : "never"}
                    {a.locked && (
                      <span className="chip-caution mt-1 inline-flex">
                        <IconLock className="h-3 w-3" /> locked
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {a.is_active && a.user_id !== subject.user_id && (
                      <form method="post" action="/actions/admin">
                        <input type="hidden" name="action" value="suspend" />
                        <input type="hidden" name="user_id" value={a.user_id} />
                        <button type="submit" className="btn-quiet text-xs">
                          Suspend
                        </button>
                      </form>
                    )}
                    {!a.is_active && (
                      <span className="chip-draft">suspended</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 3. Designations and grants. */}
      <section className="mt-10 grid gap-6 lg:grid-cols-2">
        <div>
          <h2 className="font-serif text-xl tracking-tight text-ink-900">Designate on a case</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-500">
            A designation is decisive and bounded: the officer must also be in the case&apos;s
            organization and jurisdiction, or the rule does not hold.
          </p>
          <form method="post" action="/actions/admin" className="surface mt-4 space-y-3 px-5 py-4">
            <input type="hidden" name="action" value="assign" />
            <label className="block">
              <span className="mb-1 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
                Officer
              </span>
              <select name="user_id" required className="field w-full text-xs">
                {placed
                  .filter((a) => a.is_active && !a.is_administrative)
                  .map((a) => (
                    <option key={a.user_id} value={a.user_id}>
                      {a.display_name} — {a.post_title}
                    </option>
                  ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
                Case
              </span>
              <select name="case_id" required className="field w-full text-xs">
                {(cases ?? []).map((c) => {
                  const isPrimary = c.reference === "VRN-N/2026/0001";
                  const label = isPrimary ? `VRN/26/0142 (${c.reference})` : c.reference;
                  return (
                    <option key={c.case_id} value={c.case_id}>
                      {label}
                      {c.is_sealed ? " — sealed" : ""}
                    </option>
                  );
                })}
              </select>
            </label>
            <button type="submit" className="btn-primary w-full justify-center">
              Designate
            </button>
          </form>
        </div>

        <div>
          <h2 className="font-serif text-xl tracking-tight text-ink-900">Issue a grant</h2>
          <p className="mt-1 text-xs leading-relaxed text-ink-500">
            The only route across an organization boundary. Purpose-limited, expiring, and
            never to yourself — refused here as well as by the policy at read time.
          </p>
          <form method="post" action="/actions/admin" className="surface mt-4 space-y-3 px-5 py-4">
            <input type="hidden" name="action" value="grant" />
            <label className="block">
              <span className="mb-1 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
                Grantee
              </span>
              <select name="user_id" required className="field w-full text-xs">
                {placed
                  .filter((a) => a.is_active && a.user_id !== subject.user_id)
                  .map((a) => (
                    <option key={a.user_id} value={a.user_id}>
                      {a.display_name} — {a.organization}
                    </option>
                  ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
                Case
              </span>
              <select name="case_id" required className="field w-full text-xs">
                {(cases ?? []).map((c) => {
                  const isPrimary = c.reference === "VRN-N/2026/0001";
                  const label = isPrimary ? `VRN/26/0142 (${c.reference})` : c.reference;
                  return (
                    <option key={c.case_id} value={c.case_id}>
                      {label}
                    </option>
                  );
                })}
              </select>
            </label>
            <div className="grid grid-cols-[1fr_7rem] gap-3">
              <label className="block">
                <span className="mb-1 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
                  Purpose
                </span>
                <input
                  name="purpose"
                  required
                  minLength={3}
                  maxLength={200}
                  placeholder="charge-sheet preparation"
                  className="field w-full text-xs"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
                  Days
                </span>
                <input
                  type="number"
                  name="days"
                  defaultValue={30}
                  min={1}
                  max={365}
                  className="field w-full text-xs"
                />
              </label>
            </div>
            <button type="submit" className="btn-primary w-full justify-center">
              Issue grant
            </button>
          </form>
        </div>
      </section>

      {/* Who currently holds access — AR-14. */}
      <section className="mt-10">
        <h2 className="font-serif text-xl tracking-tight text-ink-900">Who holds access now</h2>
        <p className="mt-1 text-xs leading-relaxed text-ink-500">
          Both routes, live. The threat model recorded the absence of this answer as an
          accepted risk; it is answerable here.
        </p>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="surface px-5 py-4">
            <div className="flex items-center justify-between">
              <p className="eyebrow text-ink-400">Designations (Intra-station • Original)</p>
              <span className="chip-verified text-[0.65rem]">Full Document Access</span>
            </div>
            {(access?.designations.length ?? 0) === 0 ? (
              <p className="mt-2 text-sm text-ink-500">None in force.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {access!.designations.map((d, i) => {
                  const displayRef = d.reference === "VRN-N/2026/0001" ? "VRN/26/0142" : d.reference;
                  return (
                    <li key={i} className="flex items-baseline justify-between gap-3 text-sm">
                      <span className="font-semibold text-ink-900">{d.display_name}</span>
                      <span className="font-mono text-xs text-ink-500">{displayRef}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <div className="surface px-5 py-4">
            <div className="flex items-center justify-between">
              <p className="eyebrow text-ink-400">Grants (Cross-organization • Redacted)</p>
              <span className="chip-brass text-[0.65rem]">Derivative Access Only</span>
            </div>
            {(access?.grants.length ?? 0) === 0 ? (
              <p className="mt-2 text-sm text-ink-500">None in force.</p>
            ) : (
              <ul className="mt-3 space-y-2.5">
                {access!.grants.map((g) => {
                  const displayRef = g.reference === "VRN-N/2026/0001" ? "VRN/26/0142" : g.reference;
                  return (
                    <li key={g.grant_id} className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-ink-900">{g.display_name}</p>
                        <p className="text-xs text-ink-500">
                          <span className="font-mono font-medium text-ink-700">{displayRef}</span> · {g.purpose} ·
                          expires {relative(g.expires_at)}
                        </p>
                      </div>
                      <form method="post" action="/actions/admin">
                        <input type="hidden" name="action" value="revoke" />
                        <input type="hidden" name="grant_id" value={g.grant_id} />
                        <button type="submit" className="btn-quiet text-xs">
                          Revoke
                        </button>
                      </form>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </section>

      <p className="mt-10 text-xs leading-relaxed text-ink-400">
        This screen lists case <em>references</em> so that a case can be picked. That is
        metadata about cases this account cannot open, and it is a real disclosure — recorded
        as AR-19 rather than left implicit. It shows no document, no extracted field, no party
        and no OCR text, and the administrative policy names no predicate that could reach one.
      </p>
      </div>
    </Shell>
  );
}
