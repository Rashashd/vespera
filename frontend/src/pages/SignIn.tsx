/**
 * Sign-in page — finalized split layout from the "Pantera Login Split" design
 * handoff. Left brand panel (lockup, the "Why Pantera?" note, a faded panther
 * watermark, ambient orbs + vignette); right form panel (heading, tagline,
 * real sign-in form, theme toggle). Both panels follow the active theme, so
 * light mode is light edge-to-edge. Stacks to the form alone on narrow screens.
 */
import { LoginForm } from "@/components/auth/LoginForm";
import { PantherMark } from "@/components/PantherMark";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Wordmark } from "@/components/Wordmark";

export default function SignIn() {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.12fr_0.88fr]">
      {/* ░░ Brand panel ░░ */}
      <div className="login-brand relative hidden flex-col justify-between overflow-hidden p-14 lg:flex">
        {/* ambient depth */}
        <div className="login-orb-1 pointer-events-none absolute -left-[8%] -top-[12%] h-[500px] w-[520px] rounded-full blur-[120px]" />
        <div className="login-orb-2 pointer-events-none absolute -bottom-[16%] -right-[10%] h-[520px] w-[560px] rounded-full blur-[120px]" />
        {/* faded panther watermark, bleeding off the lower-right */}
        <PantherMark
          variant="mono"
          className="pointer-events-none absolute -bottom-[12%] -right-[14%] h-[88%] w-auto text-pantera-teal opacity-[0.13] mix-blend-multiply dark:text-pantera-tealLt dark:opacity-20 dark:mix-blend-screen"
        />
        {/* vignette */}
        <div className="login-vignette pointer-events-none absolute inset-0" />

        {/* lockup */}
        <Wordmark
          iconClassName="h-24 w-24"
          textClassName="text-[34px] text-foreground"
          className="relative z-10"
        />

        {/* story */}
        <div className="relative z-10 max-w-[440px]">
          <div className="mb-5 font-mono text-[10.5px] uppercase tracking-[0.26em] text-pantera-teal dark:text-pantera-tealLt">
            Why Pantera?
          </div>
          <h2 className="mb-5 font-display text-[25px] font-medium leading-[1.32] tracking-[-0.01em] text-foreground">
            Stealth, sharp senses,
            <br />
            constant vigilance.
          </h2>
          <p className="text-[14.5px] leading-[1.72] text-[#4a6580] dark:text-[#9db0c2]">
            A panther watches quietly and continuously — exactly how Pantera
            monitors the medical literature for danger signals before they
            become crises.
          </p>
        </div>

        {/* trust strip */}
        <div className="relative z-10 flex items-center gap-[10px] font-mono text-[9.5px] uppercase tracking-[0.24em] text-[#8195a8] dark:text-[#4e6478]">
          <span>Regulated</span>
          <span className="opacity-45">·</span>
          <span>Compliant</span>
          <span className="opacity-45">·</span>
          <span>Auditable</span>
        </div>
      </div>

      {/* ░░ Form panel ░░ */}
      <div className="login-form relative flex items-center justify-center p-12">
        <div className="absolute right-6 top-6">
          <ThemeToggle />
        </div>

        <div className="w-full max-w-[368px]">
          {/* compact lockup for narrow screens (brand panel is hidden there) */}
          <Wordmark
            iconClassName="h-12 w-12"
            textClassName="text-2xl text-foreground"
            className="mb-8 lg:hidden"
          />

          <h1 className="mb-2 font-display text-[26px] font-semibold tracking-[-0.015em] text-foreground">
            Sign in to your console
          </h1>
          <p className="mb-[34px] font-mono text-[11px] uppercase tracking-[0.2em] text-pantera-teal dark:text-pantera-tealLt">
            Automated vigilance. Human precision.
          </p>

          <LoginForm />
        </div>
      </div>
    </div>
  );
}
