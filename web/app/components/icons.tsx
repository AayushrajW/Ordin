/**
 * Icons, drawn inline. No icon font and no package: an icon library is a dependency
 * shipped into the judge's browser (threat SUP-04) for twenty shapes.
 * Stroke-based, 1.6px, on a 20px grid, so they sit on the text baseline.
 */
type P = { className?: string };

function Svg({ className = "h-4 w-4", children }: P & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className={className}
    >
      {children}
    </svg>
  );
}

export const IconCases = (p: P) => (
  <Svg {...p}><path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h3.2l1.6 1.6h6.2A1.5 1.5 0 0 1 17 8.1v6.4a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5z" /></Svg>
);
export const IconShield = (p: P) => (
  <Svg {...p}><path d="M10 2.8 4 5v4.6c0 3.7 2.5 6.4 6 7.6 3.5-1.2 6-3.9 6-7.6V5z" /><path d="m7.4 10 1.8 1.8 3.5-3.6" /></Svg>
);
export const IconPulse = (p: P) => (
  <Svg {...p}><path d="M2.5 10h3.2l1.8-4.5 3 9 1.9-4.5h5.1" /></Svg>
);
export const IconLock = (p: P) => (
  <Svg {...p}><rect x="4.5" y="9" width="11" height="8" rx="1.6" /><path d="M7 9V6.6a3 3 0 0 1 6 0V9" /></Svg>
);
export const IconDoc = (p: P) => (
  <Svg {...p}><path d="M5.5 2.8h6l3 3v11.4H5.5z" /><path d="M11.5 2.8v3h3M8 10h4.5M8 13h4.5" /></Svg>
);
export const IconCheck = (p: P) => (
  <Svg {...p}><path d="m4.5 10.5 3.3 3.2L15.5 6" /></Svg>
);
export const IconAlert = (p: P) => (
  <Svg {...p}><path d="M10 3 2.8 16h14.4z" /><path d="M10 8.2v3.6M10 14h.01" /></Svg>
);
export const IconX = (p: P) => (
  <Svg {...p}><path d="m5.5 5.5 9 9m0-9-9 9" /></Svg>
);
export const IconArrowRight = (p: P) => (
  <Svg {...p}><path d="M4 10h11.5m-4.5-4.5L15.5 10 11 14.5" /></Svg>
);
export const IconSearch = (p: P) => (
  <Svg {...p}><circle cx="9" cy="9" r="5.2" /><path d="m12.8 12.8 3.7 3.7" /></Svg>
);
export const IconChevron = (p: P) => (
  <Svg {...p}><path d="m8 5 5 5-5 5" /></Svg>
);
export const IconUpload = (p: P) => (
  <Svg {...p}><path d="M10 13.5V3.5m-4 4 4-4 4 4M3.5 13.5v2.2A1.3 1.3 0 0 0 4.8 17h10.4a1.3 1.3 0 0 0 1.3-1.3v-2.2" /></Svg>
);
export const IconRedact = (p: P) => (
  <Svg {...p}><rect x="3" y="4.5" width="14" height="3.4" rx="0.8" fill="currentColor" stroke="none" /><rect x="3" y="11.5" width="9" height="3.4" rx="0.8" fill="currentColor" stroke="none" /><path d="M14.5 13.2h2.5" /></Svg>
);
export const IconChain = (p: P) => (
  <Svg {...p}><path d="M8.2 11.8 11.8 8.2" /><path d="M9 6.2 10.4 4.8a3 3 0 0 1 4.3 4.3L13.3 10.5M10.9 13.8 9.5 15.2a3 3 0 0 1-4.3-4.3l1.4-1.4" /></Svg>
);
export const IconEye = (p: P) => (
  <Svg {...p}><path d="M2.5 10s2.8-5 7.5-5 7.5 5 7.5 5-2.8 5-7.5 5-7.5-5-7.5-5z" /><circle cx="10" cy="10" r="2.2" /></Svg>
);
export const IconPen = (p: P) => (
  <Svg {...p}><path d="M13.2 3.8a1.9 1.9 0 0 1 2.7 2.7L7.2 15.2l-3.5.9.9-3.5z" /></Svg>
);
export const IconSpark = (p: P) => (
  <Svg {...p}><path d="M10 2.8v3.4M10 13.8v3.4M2.8 10h3.4M13.8 10h3.4M5 5l2.2 2.2M12.8 12.8 15 15M15 5l-2.2 2.2M7.2 12.8 5 15" /></Svg>
);
export const IconUser = (p: P) => (
  <Svg {...p}><circle cx="10" cy="7" r="3.2" /><path d="M3.8 17c.8-3.2 3.3-5 6.2-5s5.4 1.8 6.2 5" /></Svg>
);
export const IconLogout = (p: P) => (
  <Svg {...p}><path d="M12 6V4.5A1.5 1.5 0 0 0 10.5 3h-5A1.5 1.5 0 0 0 4 4.5v11A1.5 1.5 0 0 0 5.5 17h5a1.5 1.5 0 0 0 1.5-1.5V14M9 10h8.5m-3-3 3 3-3 3" /></Svg>
);
export const IconClock = (p: P) => (
  <Svg {...p}><circle cx="10" cy="10" r="7" /><path d="M10 6v4l2.8 1.8" /></Svg>
);

/** The seal. Drawn, not a raster, so it is crisp at every size and costs no request. */
export function Seal({ className = "h-9 w-9" }: P) {
  return (
    <svg viewBox="0 0 40 40" aria-hidden className={className}>
      <defs>
        <linearGradient id="seal-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#E4C487" />
          <stop offset="0.55" stopColor="#B08236" />
          <stop offset="1" stopColor="#7A5820" />
        </linearGradient>
      </defs>
      <circle cx="20" cy="20" r="19" fill="url(#seal-g)" />
      <circle cx="20" cy="20" r="15.2" fill="none" stroke="#0B1222" strokeOpacity="0.35" strokeWidth="0.8" strokeDasharray="1.4 1.6" />
      <path d="M20 9.5 13 12.2v5.6c0 4.6 3 8 7 9.6 4-1.6 7-5 7-9.6v-5.6z" fill="#0B1222" />
      <path d="M16.6 18.6 19 21l4.6-4.7" fill="none" stroke="#E4C487" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
