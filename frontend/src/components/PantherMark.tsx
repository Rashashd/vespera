/**
 * Pantera panther mark — the brand icon inlined as SVG (path data from the
 * finalized "Pantera Login Split" handoff) so it renders crisply at any size
 * and recolors per theme. Continuous teal line + three red signal nodes.
 *
 * - variant="brand" (default): teal line + red nodes, brighter in dark mode.
 * - variant="mono": single-colour strokes that inherit `currentColor` — used
 *   for the large faded watermark (set colour + opacity on the parent).
 *
 * Size it with width/height utilities (e.g. `h-12 w-12`).
 */
export function PantherMark({
  className = "",
  variant = "brand",
}: {
  className?: string;
  variant?: "brand" | "mono";
}) {
  const mono = variant === "mono";
  const lineStroke = mono
    ? "stroke-current"
    : "stroke-pantera-teal dark:stroke-[#2aa5a5]";
  const nodeStroke = mono
    ? "stroke-current"
    : "stroke-pantera-alert dark:stroke-[#bf5050]";
  return (
    <svg
      viewBox="0 0 800 800"
      role="img"
      aria-label="Pantera"
      className={className}
      fill="none"
      strokeLinejoin="round"
      strokeLinecap="round"
      xmlns="http://www.w3.org/2000/svg"
    >
      <g className={lineStroke} strokeWidth={26}>
        <path d="M624.35,425l66.74,66.28a1.74,1.74,0,0,0,3-1.25l-1.2-167.56-91.47-99.81L493.81,247.23l79.21-50,20.73-74.07-94.93,40.26s-149.42-35.22-250.6-.9l-55.35,81.09-97.23,77,39.71,79.61,17,3.47-4.81,22.81,41.77,51.79,49.45,22.6L270.34,462" />
        <path d="M573.91,561.18S331.25,415.35,270.34,462" />
        <path d="M404,600.1c-.27-.06-45.67-44.77-45.67-44.77l63.9-71.07" />
      </g>
      <g className={nodeStroke} strokeWidth={24}>
        <circle cx="602.46" cy="580.89" r="31.92" />
        <circle cx="425.88" cy="623.79" r="31.92" />
        <circle cx="606.01" cy="404.18" r="31.92" />
      </g>
    </svg>
  );
}
