// Atlas's mark: a globe reduced to its coordinate lines — meridians and a
// latitude band — with one small accent point, standing in for "a place you
// can ask about." Drawn as inline SVG (no external asset, no new
// dependency) using the same --navy/--accent tokens as the rest of the UI,
// so it already matches both themes in globals.css without its own
// light/dark handling.
export default function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <circle cx="16" cy="16" r="13" stroke="var(--navy)" strokeWidth="1.6" />
      <ellipse cx="16" cy="16" rx="5.5" ry="13" stroke="var(--navy)" strokeWidth="1.3" opacity="0.75" />
      <path d="M3 16 H29" stroke="var(--navy)" strokeWidth="1.3" opacity="0.75" />
      <path d="M5.5 9.5 H26.5" stroke="var(--navy)" strokeWidth="1" opacity="0.4" />
      <path d="M5.5 22.5 H26.5" stroke="var(--navy)" strokeWidth="1" opacity="0.4" />
      <circle cx="20.5" cy="12" r="2.1" fill="var(--accent)" />
    </svg>
  );
}
