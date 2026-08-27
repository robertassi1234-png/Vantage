import { createContext, useContext } from "react";
import type { Account } from "./types";

/**
 * Who is signed in, readable anywhere.
 *
 * Several panels change what they say depending on whether lists are kept in
 * this browser or on an account. A context beats threading a boolean through
 * every page, and beats each panel fetching the account for itself.
 */
export const SIGNED_OUT: Account = {
  signed_in: false,
  email: null,
  accounts_available: false,
  durable_storage: false,
  email_delivery: false,
  reason: null,
};

const AccountContext = createContext<Account>(SIGNED_OUT);

export const AccountProvider = AccountContext.Provider;

export function useCurrentAccount(): Account {
  return useContext(AccountContext);
}
