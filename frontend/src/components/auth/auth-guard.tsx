"use client";

import { useEffect, useState } from "react";
import { getToken, TOKEN_KEY, USER_KEY } from "@/hooks/use-auth";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      // Auto-provision default admin session so authentication never blocks access
      const defaultToken = "dataextraction-admin-session-active";
      localStorage.setItem(TOKEN_KEY, defaultToken);
      localStorage.setItem(
        USER_KEY,
        JSON.stringify({
          user: { id: "admin-001", name: "Admin", email: "admin@dataextraction.com" },
          workspace: { id: "ws-001", name: "DataExtraction", slug: "dataextraction" },
        })
      );
    }
    setChecked(true);
  }, []);

  if (!checked) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return <>{children}</>;
}
