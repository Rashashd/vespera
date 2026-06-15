import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useLogin } from "@/auth/useLogin";
import { defaultLandingFor } from "@/components/RequireRole";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/api/client";
import type { User } from "@/api/schemas";

export default function SignIn() {
  const navigate = useNavigate();
  const location = useLocation();
  const { mutate: login, isPending } = useLogin();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 rounded-lg border bg-card p-8 shadow-sm">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold text-primary">Pantera PV</h1>
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
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
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
