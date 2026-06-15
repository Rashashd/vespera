import { useMutation } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import { UserSchema } from "@/api/schemas";
import { useAuth } from "./AuthContext";

interface LoginForm {
  username: string;
  password: string;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
}

export function useLogin() {
  const { setAuth } = useAuth();

  return useMutation({
    mutationFn: async ({ username, password }: LoginForm) => {
      // fastapi-users expects form-encoded body for JWT login
      const formData = new URLSearchParams({ username, password });
      const tokenResp = await apiClient<TokenResponse>("/auth/jwt/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: formData.toString(),
      });

      // Fetch current user to get role/scope. The token isn't in storage yet (setAuth runs
      // below), so attach it explicitly — otherwise this request is unauthenticated (401).
      const rawUser = await apiClient<unknown>("/auth/users/me", {
        headers: { Authorization: `Bearer ${tokenResp.access_token}` },
      });
      const user = UserSchema.parse(rawUser);

      setAuth(tokenResp.access_token, user);
      return user;
    },
  });
}
