import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { sendPasswordResetEmail, signInWithCustomToken } from "firebase/auth";
import { browserSupportsWebAuthn, startAuthentication } from "@simplewebauthn/browser";
import { useAuth } from "../contexts/AuthContext";
import { auth } from "../lib/firebase";
import { publicPost } from "../lib/api";
import { usernameToAuthEmail } from "../lib/authIdentity";

interface LockoutReport {
  locked: boolean;
  remaining: number;
  threshold: number;
  window_minutes: number;
}

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [focusedField, setFocusedField] = useState<"username" | "password" | null>(null);
  const [bioLoading, setBioLoading] = useState(false);
  const [bioSupported] = useState(browserSupportsWebAuthn());

  const handleBiometric = async () => {
    setError("");
    setInfo("");
    const cleanEmail = usernameToAuthEmail(username);
    if (!cleanEmail) {
      setError("Enter your username above first, then tap the biometric button.");
      return;
    }
    setBioLoading(true);
    try {
      // 1. Request an assertion challenge scoped to this user's registered passkeys.
      const start = await publicPost<{
        options: Record<string, unknown>;
        challenge_id: string;
        has_credentials: boolean;
      }>("/webauthn/login/start", { email: cleanEmail });
      if (!start) throw new Error("Could not reach the server for biometric sign-in.");
      if (!start.has_credentials) {
        setError(
          "No passkeys are registered for this username. Sign in with your password first, then register one on your Profile page.",
        );
        return;
      }

      // 2. Invoke the browser's passkey prompt. This triggers Face ID / Touch ID /
      //    Windows Hello / Android biometric natively.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const assertion = await startAuthentication(start.options as any);

      // 3. Send the assertion back; server mints a Firebase custom token.
      const finish = await publicPost<{ firebase_token: string; email: string }>(
        "/webauthn/login/finish",
        { challenge_id: start.challenge_id, credential: assertion },
      );
      if (!finish || !finish.firebase_token) {
        throw new Error("Biometric verification failed. Try again or use your password.");
      }

      // 4. Exchange the custom token for a real Firebase session.
      await signInWithCustomToken(auth, finish.firebase_token);
      void publicPost("/auth/report-successful-login", { email: cleanEmail });
      setTimeout(() => navigate("/schedule", { replace: true }), 300);
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      if (/cancell|NotAllowed/i.test(m)) {
        setError("Biometric sign-in was cancelled.");
      } else {
        setError(m.replace(/^Error:\s*/, ""));
      }
    } finally {
      setBioLoading(false);
    }
  };

  const handleForgotPassword = async () => {
    setError("");
    setInfo("");
    const cleanEmail = usernameToAuthEmail(username);
    if (!cleanEmail) {
      setError("Enter your username above first, then tap \u201CForgot password\u201D.");
      return;
    }
    setResetting(true);
    try {
      await sendPasswordResetEmail(auth, cleanEmail);
      // Firebase doesn't tell us whether the account exists (intentional, to prevent
      // user enumeration). Always show the same generic success message.
      setInfo("If that username has an account, a reset link has been sent. Check your inbox (and spam).");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Could not send reset email";
      setError(msg.includes("auth/invalid-email") ? "That doesn't look like a valid username." : "Could not send reset email. Try again in a minute.");
    } finally {
      setResetting(false);
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setInfo("");
    setLoading(true);
    const cleanEmail = usernameToAuthEmail(username);
    try {
      await login(cleanEmail, password);
      // Successful — reset the server-side failure counter for this email.
      void publicPost("/auth/report-successful-login", { email: cleanEmail });
      // Wait a moment for auth state to ripple
      setTimeout(() => {
        navigate("/schedule", { replace: true });
      }, 300);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Login failed";

      // Tell the backend about the failure so it can lock the account if this
      // email has been hitting a wall. This is fire-and-forget — we still
      // surface Firebase's own error even if the report fails.
      const report = cleanEmail
        ? await publicPost<LockoutReport>("/auth/report-failed-login", { email: cleanEmail })
        : null;

      if (report?.locked) {
        setError(
          "This account has been locked after too many failed sign-ins. Ask an owner or manager to re-enable it, or use ‘Forgot password?’ to reset.",
        );
      } else if (report && report.remaining > 0 && report.remaining <= 2) {
        setError(
          `Incorrect username or password. ${report.remaining} attempt${report.remaining === 1 ? "" : "s"} left before this account is temporarily locked.`,
        );
      } else if (msg.includes("auth/wrong-password") || msg.includes("auth/invalid-credential")) {
        setError("Incorrect username or password.");
      } else if (msg.includes("auth/user-disabled")) {
        setError("This account is disabled. Contact an owner to re-enable it.");
      } else if (msg.includes("auth/too-many-requests")) {
        setError("Too many sign-in attempts from this device. Wait a few minutes and try again.");
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 text-gray-900 transition-colors duration-300 dark:bg-black dark:text-gray-100">
      <div className="w-full max-w-sm px-6">
        <div className="flex flex-col items-center justify-center space-y-3 mb-10 mt-[-5vh]">
          {/* Authentic Brand Logo matching iOS */}
          <img 
            src="/ve-logo.avif" 
            alt="Brand Logo" 
            className="h-16 w-auto object-contain drop-shadow-md rounded-[10px]"
          />
          <div className="text-center">
            <h1 className="text-[28px] font-bold font-serif tracking-tight mt-3">VictoriaEnso</h1>
            <p className="mt-1 text-sm text-gray-500 uppercase tracking-widest font-medium">Retail Management</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col space-y-5">
          <div className="flex flex-col space-y-4">
            <div
               className={`relative rounded-xl bg-white/50 dark:bg-zinc-900/50 backdrop-blur-md transition-all duration-300 shadow-sm border
                 ${focusedField === "username" ? "border-blue-500 shadow-[0_4px_12px_rgba(59,130,246,0.2)]" : "border-gray-200 dark:border-white/10"}`}
            >
              <input
                id="username"
                type="text"
                required
                autoCapitalize="none"
                autoCorrect="off"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onFocus={() => setFocusedField("username")}
                onBlur={() => setFocusedField(null)}
                className="w-full bg-transparent px-4 py-3.5 text-base outline-none autofill:bg-transparent placeholder-gray-400 dark:placeholder-gray-500"
                placeholder="Username"
              />
            </div>

            <div
               className={`relative rounded-xl bg-white/50 dark:bg-zinc-900/50 backdrop-blur-md transition-all duration-300 shadow-sm border
                 ${focusedField === "password" ? "border-blue-500 shadow-[0_4px_12px_rgba(59,130,246,0.2)]" : "border-gray-200 dark:border-white/10"}`}
            >
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onFocus={() => setFocusedField("password")}
                onBlur={() => setFocusedField(null)}
                className="w-full bg-transparent px-4 py-3.5 text-base outline-none autofill:bg-transparent placeholder-gray-400 dark:placeholder-gray-500"
                placeholder="Password"
              />
            </div>
          </div>

          {error && (
            <div className="text-center text-sm font-medium text-red-500 -mt-2 animate-pulse">
              {error}
            </div>
          )}
          {info && (
            <div className="text-center text-sm font-medium text-green-600 dark:text-green-400 -mt-2">
              {info}
            </div>
          )}

          <div className="flex flex-col items-center space-y-4 pt-4">
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-xl bg-gray-900 dark:bg-white text-white dark:text-black py-3.5 text-[15px] font-semibold transition-all hover:opacity-90 hover:shadow-lg disabled:opacity-50 active:scale-[0.98]"
            >
              {loading ? (
                <span className="flex items-center justify-center space-x-2">
                  <svg className="h-5 w-5 animate-spin text-current" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  <span>Verifying...</span>
                </span>
              ) : "Sign In"}
            </button>

            {bioSupported && (
              <button
                type="button"
                disabled={bioLoading || loading}
                onClick={handleBiometric}
                className="flex w-full items-center justify-center space-x-2 rounded-xl border border-gray-300 bg-white dark:bg-zinc-900 dark:border-white/10 text-gray-800 dark:text-gray-100 py-3 text-[14px] font-semibold transition-all hover:border-blue-400 hover:text-blue-600 disabled:opacity-50 active:scale-[0.98]"
                title="Use Face ID, Touch ID, Windows Hello, or your device's fingerprint sensor"
              >
                {bioLoading ? (
                  <>
                    <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25"></circle><path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="4" className="opacity-75"></path></svg>
                    <span>Waiting for sensor…</span>
                  </>
                ) : (
                  <>
                    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M6.5 14.5c0-3 2.5-6 5.5-6s5.5 3 5.5 6" />
                      <path d="M4 11c0-4 3.6-7 8-7s8 3 8 7" />
                      <path d="M9 17c0-2 1.3-4 3-4s3 2 3 4" />
                      <path d="M12 20v-3" />
                    </svg>
                    <span>Sign in with Face ID / fingerprint</span>
                  </>
                )}
              </button>
            )}

            <button
              type="button"
              disabled={resetting}
              onClick={handleForgotPassword}
              className="text-sm font-medium text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors disabled:opacity-50"
            >
              {resetting ? "Sending reset email\u2026" : "Forgot password?"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
