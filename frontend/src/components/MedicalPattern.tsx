/**
 * Decorative, theme-aware medical line-art background for the sign-in screen.
 * Pure inline SVG (CSP-safe, no asset files); tiles molecule, document, DNA,
 * pill, and cross motifs that inherit `currentColor`, so callers control the
 * tint/opacity with a text-color utility class.
 */
export default function MedicalPattern({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid slice"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <pattern
          id="pv-motifs"
          x="0"
          y="0"
          width="260"
          height="260"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(-8)"
        >
          <g
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            {/* molecule */}
            <g transform="translate(26 30)">
              <circle cx="0" cy="0" r="5" />
              <circle cx="28" cy="15" r="5" />
              <circle cx="0" cy="30" r="5" />
              <line x1="4" y1="2" x2="24" y2="13" />
              <line x1="4" y1="28" x2="24" y2="17" />
            </g>

            {/* document with text lines */}
            <g transform="translate(160 28)">
              <rect x="0" y="0" width="34" height="44" rx="3" />
              <line x1="7" y1="12" x2="27" y2="12" />
              <line x1="7" y1="21" x2="27" y2="21" />
              <line x1="7" y1="30" x2="20" y2="30" />
            </g>

            {/* DNA double helix */}
            <g transform="translate(44 156)">
              <path d="M0 0 C 18 14, 18 26, 0 40" />
              <path d="M22 0 C 4 14, 4 26, 22 40" />
              <line x1="3" y1="8" x2="19" y2="8" />
              <line x1="1" y1="20" x2="21" y2="20" />
              <line x1="3" y1="32" x2="19" y2="32" />
            </g>

            {/* capsule / pill */}
            <g transform="translate(150 168) rotate(35)">
              <rect x="0" y="0" width="40" height="18" rx="9" />
              <line x1="20" y1="0" x2="20" y2="18" />
            </g>

            {/* medical cross */}
            <g transform="translate(118 112)">
              <path d="M6 0 H12 V6 H18 V12 H12 V18 H6 V12 H0 V6 H6 Z" />
            </g>
          </g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#pv-motifs)" />
    </svg>
  );
}
