/**
 * Sign-in form: email + password with reveal toggle, "remember me", a
 * non-self-serve "forgot password" hint, non-enumerating errors, and
 * post-login role-based redirect. Styled to the finalized "Pantera Login
 * Split" handoff; layout-agnostic so the page owns heading/tagline/chrome.
 */
import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { ArrowRight, Check, Eye, EyeOff } from "lucide-react";
import { useLogin } from "@/auth/useLogin";
import { defaultLandingFor } from "@/components/RequireRole";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/api/client";
import type { User } from "@/api/schemas";

const labelClass =
  "font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-[#4a6580] dark:text-[#8095a8]";
const inputClass =
  "h-12 w-full rounded-[10px] border border-input bg-background px-[15px] text-[15px] text-foreground outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-muted-foreground/50 focus:border-primary focus:ring-[3px] focus:ring-primary/20";

export function LoginForm() {
  const navigate = useNavigate();
  const location = useLocation();
  const { mutate: login, isPending } = useLogin();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [forgotOpen, setForgotOpen] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    login(
      { username: email, password },
      {
        onSuccess: (user: User) => {
          const from =
            (location.state as { from?: { pathname: string } })?.from?.pathname ??
            defaultLandingFor(user);
          navigate(from, { replace: true });
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 429) {
            setErrorMsg("Too many sign-in attempts. Please try again later.");
          } else {
            // Non-enumerating error — do not confirm whether the email exists
            setErrorMsg("Invalid email or password.");
          }
        },
      },
    );
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-[18px]" noValidate>
      {/* Email */}
      <div className="flex flex-col gap-[7px]">
        <label htmlFor="email" className={labelClass}>
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          placeholder="you@vendor.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={inputClass}
          aria-describedby={errorMsg ? "signin-error" : undefined}
        />
      </div>

      {/* Password */}
      <div className="flex flex-col gap-[7px]">
        <div className="flex items-center justify-between">
          <label htmlFor="password" className={labelClass}>
            Password
          </label>
          <button
            type="button"
            onClick={() => setShowPassword((s) => !s)}
            className="flex items-center gap-[5px] font-mono text-[10px] uppercase tracking-[0.1em] text-primary"
            aria-pressed={showPassword}
          >
            {showPassword ? (
              <EyeOff className="h-[13px] w-[13px]" />
            ) : (
              <Eye className="h-[13px] w-[13px]" />
            )}
            {showPassword ? "Hide" : "Show"}
          </button>
        </div>
        <input
          id="password"
          name="password"
          type={showPassword ? "text" : "password"}
          autoComplete="current-password"
          required
          placeholder="••••••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={inputClass}
        />
      </div>

      {/* Remember me + forgot password */}
      <div className="mt-[2px] flex items-center justify-between">
        <button
          type="button"
          onClick={() => setRemember((r) => !r)}
          className="flex items-center gap-[9px]"
          aria-pressed={remember}
        >
          <span
            className={`flex h-[18px] w-[18px] flex-shrink-0 items-center justify-center rounded-[5px] border transition-colors duration-150 ${
              remember
                ? "border-primary bg-primary"
                : "border-muted-foreground/40 bg-transparent"
            }`}
          >
            {remember && (
              <Check
                className="h-[11px] w-[11px] text-primary-foreground"
                strokeWidth={3.2}
              />
            )}
          </span>
          <span className="whitespace-nowrap text-[13.5px] text-[#4a6580] dark:text-[#8095a8]">
            Remember me
          </span>
        </button>
        <button
          type="button"
          onClick={() => setForgotOpen((o) => !o)}
          className="text-[13.5px] text-primary hover:underline"
          aria-expanded={forgotOpen}
        >
          Forgot password?
        </button>
      </div>

      {forgotOpen && (
        <p className="-mt-1 text-[13px] leading-relaxed text-[#4a6580] dark:text-[#8095a8]">
          Password resets are handled by your administrator — contact them to
          regain access.
        </p>
      )}

      {errorMsg && (
        <p id="signin-error" role="alert" className="text-sm text-destructive">
          {errorMsg}
        </p>
      )}

      <Button
        type="submit"
        disabled={isPending}
        className="mt-[10px] h-[50px] w-full gap-[9px] rounded-xl text-[15px] font-medium tracking-[0.02em]"
      >
        {isPending ? "Signing in…" : "Sign in"}
        {!isPending && <ArrowRight className="h-4 w-4" />}
      </Button>
    </form>
  );
}
