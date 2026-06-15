import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/api/client";
import { ClientSchema, type Client } from "@/api/schemas";
import { useAuth } from "./AuthContext";
import { z } from "zod";

interface ActingClientContextValue {
  clientId: number | null;
  client: Client | null;
  clients: Client[];
  setClientId: (id: number) => void;
}

const ActingClientContext = createContext<ActingClientContextValue>({
  clientId: null,
  client: null,
  clients: [],
  setClientId: () => {},
});

const STORAGE_KEY = "pantera_acting_client";

export function ActingClientProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const isStaff = user?.user_type === "staff";

  // Client-users are always locked to their own client_id
  const fixedClientId = !isStaff ? user?.client_id ?? null : null;

  const [storedId, setStoredId] = useState<number | null>(() => {
    if (!isStaff) return null;
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? parseInt(raw, 10) : null;
  });

  const { data: clients = [] } = useQuery({
    queryKey: ["clients"],
    queryFn: () =>
      get<unknown[]>("/clients").then((rows) =>
        z.array(ClientSchema).parse(rows),
      ),
    enabled: isStaff && !!user,
  });

  // Auto-select first client if staff has none stored
  useEffect(() => {
    if (isStaff && storedId === null && clients.length > 0) {
      setStoredId(clients[0].id);
      localStorage.setItem(STORAGE_KEY, String(clients[0].id));
    }
  }, [isStaff, storedId, clients]);

  const clientId = isStaff ? storedId : fixedClientId;
  const client = clients.find((c) => c.id === clientId) ?? null;

  const setClientId = useCallback((id: number) => {
    setStoredId(id);
    localStorage.setItem(STORAGE_KEY, String(id));
  }, []);

  return (
    <ActingClientContext.Provider value={{ clientId, client, clients, setClientId }}>
      {children}
    </ActingClientContext.Provider>
  );
}

export function useActingClient() {
  return useContext(ActingClientContext);
}
