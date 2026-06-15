import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { type User } from "@/api/schemas";

interface AuthState {
  token: string | null;
  user: User | null;
}

interface AuthContextValue extends AuthState {
  setAuth: (token: string, user: User) => void;
  clearAuth: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const TOKEN_KEY = "pantera_token";
const USER_KEY = "pantera_user";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    const raw = localStorage.getItem(USER_KEY);
    let user: User | null = null;
    try {
      user = raw ? (JSON.parse(raw) as User) : null;
    } catch {
      // Corrupt storage — clear it rather than white-screening the app on load.
      localStorage.removeItem(USER_KEY);
      localStorage.removeItem(TOKEN_KEY);
      return { token: null, user: null };
    }
    return { token, user };
  });

  const setAuth = useCallback((token: string, user: User) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    setState({ token, user });
  }, []);

  const clearAuth = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setState({ token: null, user: null });
  }, []);

  // Listen for 401 events fired by apiClient
  useEffect(() => {
    const handler = () => clearAuth();
    window.addEventListener("AUTH_EXPIRED", handler);
    return () => window.removeEventListener("AUTH_EXPIRED", handler);
  }, [clearAuth]);

  return (
    <AuthContext.Provider value={{ ...state, setAuth, clearAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
