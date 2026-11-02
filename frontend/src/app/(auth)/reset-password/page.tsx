"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";
import { api, ApiError } from "@/lib/api";
import { PasswordInput } from "@/components/ui/password-input";

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (f.get("password") !== f.get("confirm")) return setError("Passwords do not match");
    setBusy(true);
    setError(null);
    try {
      await api("/auth/reset-password", { method: "POST", body: { token, password: f.get("password") } });
      router.push("/login?reset=1");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Reset failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h1 className="text-xl font-bold">Choose a new password</h1>
      {!token && <Alert tone="danger" className="mt-4">This reset link is incomplete. Request a new one.</Alert>}
      {error && <Alert tone="danger" className="mt-4">{error}</Alert>}
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field label="New password" htmlFor="password" hint="At least 10 characters with upper and lower case letters and a digit.">
          <PasswordInput id="password" name="password" autoComplete="new-password" minLength={10} required />
        </Field>
        <Field label="Confirm password" htmlFor="confirm">
          <PasswordInput id="confirm" name="confirm" autoComplete="new-password" required />
        </Field>
        <Button type="submit" className="w-full" loading={busy} disabled={!token}>Update password</Button>
      </form>
    </>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}
