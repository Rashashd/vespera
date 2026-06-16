import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { useLogin } from "@/auth/useLogin";
import { defaultLandingFor } from "@/components/RequireRole";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/api/client";
import type { User } from "@/api/schemas";
import MedicalPattern from "@/components/MedicalPattern";

export default function SignIn() {
  const navigate = useNavigate();
  const location = useLocation();
  const { mutate: login, isPending } = useLogin();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background">
      <MedicalPattern className="pointer-events-none absolute inset-0 text-primary/[0.07] dark:text-primary/[0.12]" />
      <div className="relative z-10 w-full max-w-sm space-y-6 rounded-lg border bg-card/95 p-8 shadow-lg backdrop-blur-sm">
        <div className="space-y-1">
          <h1 className="text-3xl font-bold tracking-tight text-primary">
            Pantera
            <sup className="ml-0.5 align-super text-base font-medium text-muted-foreground">
              ™
            </sup>
          </h1>
          <p className="text-sm text-muted-foreground">
            Pharmacovigilance literature monitor
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-describedby={errorMsg ? "signin-error" : undefined}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <div className="relative">
              <Input
                id="password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                className="absolute inset-y-0 right-0 flex items-center px-3 text-muted-foreground hover:text-foreground"
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
                tabIndex={-1}
              >
                {showPassword ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>

          {errorMsg && (
            <p
              id="signin-error"
              role="alert"
              className="text-sm text-destructive"
            >
              {errorMsg}
            </p>
          )}

          <Button type="submit" className="w-full" disabled={isPending}>
            {isPending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}
