"use client";

/**
 * Ordin's voice assistant: hands-free reading and navigation.
 *
 * An officer working a case has their hands on paper. This reads the state of the
 * screen aloud and takes a small, fixed set of spoken commands. Four rules shape it,
 * and each one is a constraint from CLAUDE.md rather than a preference:
 *
 * **1. It never speaks an identifying value.** A room is not a private channel. It says
 * "complainant name — flagged, one character differs from this case", never the name.
 * Counts, field names, flags and states only. The same reasoning as invariant 12: the
 * screen may show it to the person entitled to see it; the air may not.
 *
 * **2. It cannot commit or redact.** Those two actions write evidence — an attestation
 * under someone's name, and the destruction of content. A misheard word must never do
 * either. Voice navigates, reads and opens the redaction *preview*; a hand presses the
 * button. Stated on the panel, not buried here.
 *
 * **3. The grammar is a fixed list, matched deterministically.** No model, no
 * interpretation, no free-form intent. An unmatched phrase is refused and the list is
 * offered. Nothing the assistant hears — and nothing in a document — can become an
 * instruction (invariant 6).
 *
 * **4. Speech output is on-device; speech input is not, and it says so.** The browser's
 * `speechSynthesis` uses the operating system's voices and makes no network call, so
 * reading aloud is safe on the air-gapped demo path. `SpeechRecognition`, in the
 * browsers that have it, streams audio to the vendor's servers — which would break
 * invariant 11. Listening is therefore **off by default**, behind a switch that says
 * plainly what turning it on does. The honest provider name is on the panel:
 * `BrowserSpeechRecognition`, maturity mvp, production adapter an on-device recogniser.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { IconAlert, IconCheck, IconEye, IconSpark, IconX } from "./icons";

export type VoiceCommand = {
  /** What to say. Matched case-insensitively against the normalised transcript. */
  phrase: string;
  /** Other ways people say the same thing. */
  aliases?: string[];
  /** Where it goes, if anywhere. */
  href?: string;
  /** What it reads out, if anything. */
  say?: string;
  /** Silences whatever is being read. */
  cancel?: boolean;
  label: string;
};

type Props = { briefing: string; commands: VoiceCommand[] };

// Minimal shapes for the Web Speech API, which TypeScript's DOM library does not carry.
type SpeechResult = { transcript: string; confidence: number };
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  onresult: ((event: { results: ArrayLike<ArrayLike<SpeechResult>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function recognizer(): Recognition | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

const normalise = (text: string) =>
  text.toLowerCase().replace(/[^a-z0-9\s]/g, " ").replace(/\s+/g, " ").trim();

export default function VoiceAssistant({ briefing, commands }: Props) {
  const [open, setOpen] = useState(false);
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState("");
  const [status, setStatus] = useState<{ tone: "ok" | "warn" | "off"; text: string }>({
    tone: "off",
    text: "Idle",
  });
  const [canListen, setCanListen] = useState(false);
  const [canSpeak, setCanSpeak] = useState(false);
  const engine = useRef<Recognition | null>(null);
  const wanted = useRef(false);

  useEffect(() => {
    setCanSpeak(typeof window !== "undefined" && "speechSynthesis" in window);
    setCanListen(recognizer() !== null);
  }, []);

  // Voices load asynchronously; `getVoices()` is empty on first call in most browsers
  // and fills in later, announced by `voiceschanged`.
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const load = () => setVoices(window.speechSynthesis.getVoices());
    load();
    window.speechSynthesis.addEventListener("voiceschanged", load);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", load);
  }, []);

  const say = useCallback(
    (text: string) => {
      if (typeof window === "undefined" || !("speechSynthesis" in window)) {
        setStatus({ tone: "warn", text: "This browser cannot speak." });
        return;
      }
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.02;
      // Prefer an Indian English voice where the system has one: the content is Indian
      // references and place names, which a default US voice mangles.
      utterance.voice =
        voices.find((v) => v.lang === "en-IN") ??
        voices.find((v) => v.lang.startsWith("en-GB")) ??
        voices.find((v) => v.lang.startsWith("en")) ??
        null;
      utterance.lang = utterance.voice?.lang ?? "en-IN";

      // **Report what actually happened.** A voice assistant that silently says nothing
      // is worse than one that admits it cannot: some embedded browsers expose
      // `speechSynthesis` and ship no voices at all, and without this the panel would
      // sit there looking as though it had spoken.
      let started = false;
      utterance.onstart = () => {
        started = true;
        setStatus({ tone: "ok", text: "Speaking" });
      };
      utterance.onend = () => setStatus({ tone: "off", text: "Idle" });
      utterance.onerror = () =>
        setStatus({ tone: "warn", text: "No usable speech voice on this device." });
      window.speechSynthesis.speak(utterance);
      window.setTimeout(() => {
        if (!started) {
          setStatus({
            tone: "warn",
            text: voices.length
              ? "The speech engine did not start."
              : "This browser has no installed voices. Windows: Settings › Time & language › Speech.",
          });
        }
      }, 900);
    },
    [voices],
  );

  const run = useCallback(
    (transcript: string) => {
      const said = normalise(transcript);
      if (!said) return;
      // Longest phrase first, so "show redacted" is never shadowed by "show".
      const ordered = [...commands].sort((a, b) => b.phrase.length - a.phrase.length);
      for (const command of ordered) {
        const forms = [command.phrase, ...(command.aliases ?? [])].map(normalise);
        if (!forms.some((form) => said.includes(form))) continue;
        setStatus({ tone: "ok", text: command.label });
        if (command.cancel && typeof window !== "undefined") {
          window.speechSynthesis.cancel();
          return;
        }
        if (command.say) say(command.say);
        if (command.href) {
          if (!command.say) say(command.label);
          window.location.href = command.href;
        }
        return;
      }
      setStatus({ tone: "warn", text: `Not a command: “${transcript.trim()}”` });
      say("That is not one of my commands.");
    },
    [commands, say],
  );

  const stop = useCallback(() => {
    wanted.current = false;
    engine.current?.stop();
    setListening(false);
    setStatus({ tone: "off", text: "Idle" });
  }, []);

  const start = useCallback(() => {
    const machine = recognizer();
    if (!machine) return;
    machine.lang = "en-IN";
    machine.continuous = false;
    machine.interimResults = false;
    machine.maxAlternatives = 1;
    machine.onresult = (event) => {
      const best = event.results[event.results.length - 1]?.[0]?.transcript ?? "";
      setHeard(best);
      run(best);
    };
    machine.onerror = (event) => {
      // `no-speech` is ordinary silence; anything else is worth showing, because the
      // usual cause is exactly the thing the switch warns about — no network.
      if (event.error !== "no-speech" && event.error !== "aborted") {
        setStatus({ tone: "warn", text: `Recogniser: ${event.error}` });
      }
    };
    machine.onend = () => {
      // One utterance per session; restart while the switch is on.
      if (wanted.current) {
        try {
          machine.start();
        } catch {
          /* already starting */
        }
      } else {
        setListening(false);
      }
    };
    engine.current = machine;
    wanted.current = true;
    try {
      machine.start();
      setListening(true);
      setStatus({ tone: "ok", text: "Listening" });
    } catch {
      setStatus({ tone: "warn", text: "The microphone could not be opened." });
    }
  }, [run]);

  useEffect(() => () => stop(), [stop]);

  // Alt+V speaks the briefing without opening anything — the hands-free case.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.altKey && event.key.toLowerCase() === "v") {
        event.preventDefault();
        say(briefing);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [briefing, say]);

  return (
    <div className="fixed bottom-5 right-5 z-50 print:hidden">
      {open && (
        <div className="mb-3 w-[22rem] overflow-hidden rounded-2xl border border-ink-700 bg-ink-900 text-ink-100 shadow-lift animate-rise">
          <div className="flex items-center justify-between border-b border-ink-800 px-4 py-3">
            <div>
              <p className="text-[0.625rem] font-semibold uppercase tracking-eyebrow text-brass-300">
                Voice assistant
              </p>
              <p className="text-sm font-semibold text-white">Reads and navigates</p>
            </div>
            <button onClick={() => setOpen(false)} aria-label="Close voice assistant"
                    className="btn-ghost-ink px-2 py-1">
              <IconX className="h-4 w-4" />
            </button>
          </div>

          <div className="space-y-3 px-4 py-3">
            <button onClick={() => say(briefing)} disabled={!canSpeak} className="btn-brass w-full">
              <IconEye className="h-4 w-4" /> Read this screen
            </button>
            {canSpeak && voices.length === 0 && (
              <p className="flex gap-2 rounded-lg border border-caution-500/30 bg-caution-500/10 px-3 py-2 text-[0.6875rem] leading-snug text-caution-100">
                <IconAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                No speech voices are installed for this browser, so nothing will be heard.
                On Windows: Settings › Time &amp; language › Speech › Manage voices.
              </p>
            )}

            <div className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-2.5">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-semibold text-white">Listen for commands</span>
                <button
                  onClick={() => (listening ? stop() : start())}
                  disabled={!canListen}
                  aria-pressed={listening}
                  className={`rounded-full px-3 py-1 text-[0.6875rem] font-semibold transition ${
                    listening ? "bg-danger-500 text-white" : "bg-ink-700 text-ink-100 hover:bg-ink-600"
                  } disabled:opacity-40`}
                >
                  {listening ? "Stop" : "Start"}
                </button>
              </div>
              <p className="mt-2 flex gap-2 text-[0.6875rem] leading-snug text-caution-100/80">
                <IconAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-caution-100" />
                {canListen ? (
                  <span>
                    <span className="font-semibold">Off by default:</span> the browser&apos;s
                    recogniser streams audio to its vendor, which the offline demo path
                    forbids. Reading aloud is on-device and makes no network call.
                  </span>
                ) : (
                  <span>This browser has no speech recogniser. Reading aloud still works.</span>
                )}
              </p>
            </div>

            <div className="flex items-center gap-2 text-[0.6875rem]">
              <span className={`dot ${status.tone === "ok" ? "bg-verified-500 animate-pulse-ring" : status.tone === "warn" ? "bg-caution-500" : "bg-ink-600"}`} />
              <span className={status.tone === "warn" ? "text-caution-100" : "text-ink-300"}>{status.text}</span>
              {heard && <span className="ml-auto truncate text-ink-500">heard: {heard}</span>}
            </div>

            <div>
              <p className="text-[0.625rem] font-semibold uppercase tracking-eyebrow text-ink-500">
                Say
              </p>
              <ul className="mt-1.5 space-y-1">
                {commands.map((c) => (
                  <li key={c.phrase} className="flex items-baseline justify-between gap-3 text-[0.6875rem]">
                    <button onClick={() => run(c.phrase)} className="text-left font-mono text-brass-300 hover:underline">
                      “{c.phrase}”
                    </button>
                    <span className="truncate text-ink-300">{c.label}</span>
                  </li>
                ))}
              </ul>
            </div>

            <p className="border-t border-ink-800 pt-2.5 text-[0.625rem] leading-snug text-ink-500">
              It never speaks names, numbers or addresses aloud, and it cannot commit a
              value or burn a redaction — those write evidence, and a misheard word must
              not. <span className="text-ink-300">BrowserSpeechRecognition · maturity mvp ·
              production adapter: an on-device recogniser.</span>
            </p>
          </div>
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Voice assistant"
        className={`grid h-12 w-12 place-items-center rounded-full border border-brass-400/40 bg-ink-900 text-brass-300 shadow-lift transition hover:scale-105 ${
          listening ? "animate-pulse-ring" : ""
        }`}
      >
        {status.tone === "ok" && !open ? <IconCheck className="h-5 w-5" /> : <IconSpark className="h-5 w-5" />}
      </button>
    </div>
  );
}
