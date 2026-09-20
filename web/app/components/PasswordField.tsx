"use client";

/**
 * A password input with a reveal toggle.
 *
 * **The toggle only appears once the component has hydrated.** Changing an input's
 * `type` cannot be done in CSS, so the button needs JavaScript to do anything — and a
 * button that is painted in the server HTML and does nothing until (or unless) a script
 * runs is the failure mode this project keeps finding in other people's software: a
 * control that looks present and is not. Without JavaScript the field is an ordinary
 * password box, which is exactly right.
 *
 * `autoComplete` is passed through so a password manager still recognises the field;
 * the value is never read, stored or echoed anywhere by this component.
 */
import { useEffect, useId, useState } from "react";

export default function PasswordField({
  name = "password",
  label = "Password",
  autoComplete = "current-password",
  minLength,
  hint,
  required = true,
}: {
  name?: string;
  label?: string;
  autoComplete?: string;
  minLength?: number;
  hint?: string;
  required?: boolean;
}) {
  const [revealed, setRevealed] = useState(false);
  const [mounted, setMounted] = useState(false);
  const id = useId();

  useEffect(() => setMounted(true), []);

  return (
    <label className="block" htmlFor={id}>
      <span className="mb-1.5 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
        {label}
      </span>
      <span className="relative block">
        <input
          id={id}
          type={revealed ? "text" : "password"}
          name={name}
          required={required}
          minLength={minLength}
          autoComplete={autoComplete}
          className="field w-full pr-[4.5rem]"
        />
        {mounted && (
          <button
            type="button"
            onClick={() => setRevealed((v) => !v)}
            aria-pressed={revealed}
            aria-label={revealed ? "Hide password" : "Show password"}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md px-2.5 py-1
                       text-[0.7rem] font-semibold uppercase tracking-[0.08em]
                       text-ink-400 transition hover:bg-paper-200 hover:text-ink-700
                       focus:outline-none focus-visible:ring-2 focus-visible:ring-brass-400"
          >
            {revealed ? "Hide" : "Show"}
          </button>
        )}
      </span>
      {hint && (
        <span className="mt-1.5 block text-[0.7rem] leading-relaxed text-ink-400">{hint}</span>
      )}
    </label>
  );
}
