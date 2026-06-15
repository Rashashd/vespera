import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (count, err) => {
        // Don't retry on 401/403/404
        if (err && typeof err === "object" && "status" in err) {
          const s = (err as { status: number }).status;
          if (s === 401 || s === 403 || s === 404) return false;
        }
        return count < 2;
      },
    },
  },
});
