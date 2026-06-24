/**
 * Pantera lockup — the panther icon (brand SVG, teal, reads on any background)
 * beside or above the "PANTERA™" wordmark set in Montserrat to match the logo
 * art. Wordmark color is inherited from the parent (`text-foreground`,
 * `text-pantera-cloud`, …). Optional tagline mirrors the logo lockup.
 */
import { PantherMark } from "@/components/PantherMark";

interface WordmarkProps {
  orientation?: "horizontal" | "vertical";
  iconClassName?: string;
  textClassName?: string;
  showTagline?: boolean;
  className?: string;
}

export function Wordmark({
  orientation = "horizontal",
  iconClassName = "h-9 w-9",
  textClassName = "text-2xl",
  showTagline = false,
  className = "",
}: WordmarkProps) {
  const vertical = orientation === "vertical";
  return (
    <div
      className={`flex ${
        vertical ? "flex-col items-start gap-3" : "items-center gap-3"
      } ${className}`}
    >
      <PantherMark className={iconClassName} />
      <div className={vertical ? "" : "leading-none"}>
        <span
          className={`block font-wordmark font-medium uppercase leading-none tracking-[0.22em] ${textClassName}`}
        >
          Vespera
          <sup className="ml-[0.18em] align-super font-sans text-[0.3em] font-normal tracking-normal text-muted-foreground">
            ™
          </sup>
        </span>
        {showTagline && (
          <span className="mt-2 block font-mono text-[0.625rem] uppercase tracking-[0.2em] text-pantera-tealLt">
            Automated vigilance · Human precision
          </span>
        )}
      </div>
    </div>
  );
}
