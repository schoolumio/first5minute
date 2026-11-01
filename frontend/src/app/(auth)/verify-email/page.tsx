"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { Skeleton } from "@/components/ui/feedback";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function Verify() {
  const token = useSearchParams().get("token");
  const { refresh } = useAuth();
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [message, setMessage] = useState("");
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    if (!token) {
      setState("error");
      setMessage("This verification link is incomplete.");
      return;
    }
    api("/auth/verify-email", { method: "POST", body: { token } })
      .then(() => {
        setState("ok");
        refresh();
      })
      .catch((e) => {
        setState("error");
        setMessage(e instanceof ApiError ? e.message : "Verification failed");
      });
  }, [token, refresh]);

  if (state === "working") return <Skeleton className="h-24" />;
  return (
    <div className="text-center">
      {state === "ok" ? <CheckCircle2 className="mx-auto h-10 w-10 text-brand-500" /> : <XCircle className="mx-auto h-10 w-10 text-danger" />}
      <h1 className="mt-4 text-xl font-bold">{state === "ok" ? "Email verified" : "Verification failed"}</h1>
      <p className="mt-2 text-sm text-muted">{state === "ok" ? "Your account is fully activated." : `${message} Request a new link from your dashboard.`}</p>
      <Link href="/dashboard" className="mt-6 inline-block text-sm font-semibold text-brand-400 hover:underline">Go to dashboard</Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <Verify />
    </Suspense>
  );
}
