import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Account } from "./types";

/**
 * Whether anyone is signed in, and what this server can actually do.
 *
 * The app works signed out -- lists key on the browser instead -- so a failed
 * account lookup is not an error state. It just means "carry on anonymously",
 * which is also what a server without accounts configured looks like.
 */
const SIGNED_OUT: Account = {
  signed_in: false,
  email: null,
  accounts_available: false,
  durable_storage: false,
  email_delivery: false,
  reason: null,
};

export function useAccount() {
  const [account, setAccount] = useState<Account>(SIGNED_OUT);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setAccount(await api.getAccount());
    } catch {
      // An older backend has no /api/auth/me at all. Staying anonymous is the
      // right answer, not an error banner.
      setAccount(SIGNED_OUT);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    try {
      await api.signOut();
    } finally {
      await refresh();
    }
  }, [refresh]);

  return { account, loading, refresh, signOut };
}
