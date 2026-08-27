import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AccountProvider, SIGNED_OUT } from "../AccountContext";
import { BackupPanel } from "./BackupPanel";
import type { Account } from "../types";

vi.mock("../api", () => ({ api: { exportWorkspace: vi.fn(), importWorkspace: vi.fn() } }));

const renderWith = (account: Account) =>
  render(
    <AccountProvider value={account}>
      <BackupPanel />
    </AccountProvider>,
  );

describe("BackupPanel", () => {
  it("warns that lists are browser-only when signed out", () => {
    renderWith(SIGNED_OUT);
    expect(screen.getByText(/live in this browser only/i)).toBeInTheDocument();
  });

  it("stops claiming browser-only once signed in", () => {
    // The account already syncs across devices; saying otherwise is just wrong.
    renderWith({ ...SIGNED_OUT, signed_in: true, email: "a@b.com" });

    expect(screen.queryByText(/live in this browser only/i)).not.toBeInTheDocument();
    expect(screen.getByText(/saved to your account/i)).toBeInTheDocument();
  });

  it("still offers both actions either way", () => {
    renderWith({ ...SIGNED_OUT, signed_in: true, email: "a@b.com" });
    expect(screen.getByRole("button", { name: /download backup/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /restore from file/i })).toBeInTheDocument();
  });
});
