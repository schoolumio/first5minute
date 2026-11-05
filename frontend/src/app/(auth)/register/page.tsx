"use client";

import Link from "next/link";
import { useState } from "react";
import { MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form";
import { api, ApiError } from "@/lib/api";
import { PasswordInput } from "@/components/ui/password-input";

const COUNTRIES = [
  ["NG", "Nigeria"], ["GH", "Ghana"], ["KE", "Kenya"], ["ZA", "South Africa"], ["GB", "United Kingdom"],
  ["IE", "Ireland"], ["US", "United States"], ["CA", "Canada"], ["DE", "Germany"], ["FR", "France"], ["ES", "Spain"],
  ["IT", "Italy"], ["BR", "Brazil"], ["IN", "India"], ["AU", "Australia"],
];

export default function RegisterPage() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (f.get("password") !== f.get("confirm")) return setError("Passwords do not match");
    setBusy(true);
    setError(null);
    try {
      await api("/auth/register", {
        method: "POST",
        body: {
          email: f.get("email"), password: f.get("password"), full_name: f.get("full_name") || null,
          country: f.get("country") || null, accept_terms: f.get("terms") === "on", confirm_age: f.get("age") === "on",
        },
      });
      setDone(String(f.get("email")));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  if (done)
    return (
      <div className="text-center">
        <MailCheck className="mx-auto h-10 w-10 text-brand-500" />
        <h1 className="mt-4 text-xl font-bold">Check your email</h1>
        <p className="mt-2 text-sm text-muted">We sent a verification link to <span className="text-fg">{done}</span>. It expires in 24 hours.</p>
        <Link href="/login" className="mt-6 inline-block text-sm font-semibold text-brand-400 hover:underline">Continue to sign in</Link>
      </div>
    );

  return (
    <>
      <h1 className="font-[family-name:var(--font-display)] text-4xl font-semibold uppercase tracking-wide">Create your account</h1>
      <p className="mt-1 text-sm text-muted">Free plan included - no card required.</p>
      {error && <Alert tone="danger" className="mt-4">{error}</Alert>}
      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field label="Full name" htmlFor="full_name">
          <Input id="full_name" name="full_name" autoComplete="name" maxLength={120} />
        </Field>
        <Field label="Email" htmlFor="email">
          <Input id="email" name="email" type="email" autoComplete="email" required />
        </Field>
        <Field label="Country" htmlFor="country">
          <Select id="country" name="country" defaultValue="NG">
            {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </Select>
        </Field>
        <Field label="Password" htmlFor="password" hint="At least 10 characters with upper and lower case letters and a digit.">
          <PasswordInput id="password" name="password" autoComplete="new-password" minLength={10} required />
        </Field>
        <Field label="Confirm password" htmlFor="confirm">
          <PasswordInput id="confirm" name="confirm" autoComplete="new-password" required />
        </Field>
        <Checkbox name="age" required label="I am 18 or older (or the legal betting age where I live)." />
        <Checkbox name="terms" required label="I understand First5Minute provides statistical estimates, not guaranteed outcomes, and I accept the terms." />
        <Button type="submit" className="w-full" loading={busy}>Create account</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        Already registered? <Link href="/login" className="font-semibold text-brand-400 hover:underline">Sign in</Link>
      </p>
    </>
  );
}
