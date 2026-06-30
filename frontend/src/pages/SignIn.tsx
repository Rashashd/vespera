/**
 * Sign-in page — finalized split layout from the "Vespera Login Split" design
 * handoff. Left brand panel (lockup, the "Why Vespera?" note, a faded brand-mark
 * watermark, ambient orbs + vignette); right form panel (heading, tagline,
 * real sign-in form, theme toggle). Both panels follow the active theme, so
 * light mode is light edge-to-edge. Stacks to the form alone on narrow screens.
 */
import { LoginForm } from "@/components/auth/LoginForm";
import { VesperaMark } from "@/components/VesperaMark";
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
        {/* faded brand-mark watermark, bleeding off the lower-right */}
        <VesperaMark
          variant="brand"
          className="pointer-events-none absolute -bottom-[15%] -right-[26%] h-[84%] w-auto opacity-[0.08] dark:opacity-[0.12]"
        />
        {/* vignette */}
        <div className="login-vignette pointer-events-none absolute inset-0" />

        {/* lockup — full logo (theme-swapped) */}
        <div className="relative z-10">
          <img
            src="/vespera-logo-light.svg"
            alt="Vespera — automated vigilance, human precision"
            className="block h-auto w-[430px] dark:hidden"
          />
          <img
            src="/vespera-logo-dark.svg"
            alt="Vespera — automated vigilance, human precision"
            className="hidden h-auto w-[430px] dark:block"
          />
        </div>

        {/* story */}
        <div className="relative z-10 max-w-[440px]">
          <div className="mb-5 font-mono text-[12px] uppercase tracking-[0.26em] text-vespera-teal dark:text-vespera-tealLt">
            Why Vespera?
          </div>
          <h2 className="mb-5 font-display text-[29px] font-medium leading-[1.3] tracking-[-0.01em] text-foreground">
            One star rises over the cedar
            <br />
            and stays, keeping watch.
          </h2>
          <p className="text-[16px] leading-[1.7] text-[#4a6580] dark:text-[#9db0c2]">
            Vespera carries that name and promise: a constant vigil over the
            medical literature, so the signals that protect lives are never
            missed.
          </p>
        </div>

        {/* trust strip */}
        <div className="relative z-10 flex items-center gap-[10px] font-mono text-[10px] font-bold uppercase tracking-[0.24em] text-[#5f718a] dark:text-[#8093a8]">
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
          <p className="mb-[34px] font-mono text-[11px] uppercase tracking-[0.2em] text-vespera-teal dark:text-vespera-tealLt">
            Automated vigilance. Human precision.
          </p>

          <LoginForm />
        </div>
      </div>
    </div>
  );
}
