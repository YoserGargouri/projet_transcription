import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "@/styles/tokens.css";
import "@/styles/base.css";
import "@/styles/ui.css";
import "@/styles/marketing.css";
import "@/styles/app.css";
import { AuthProvider, RequireAuth } from "@/lib/auth";
import { ToastProvider } from "@/lib/ui-state";
import { PublicLayout } from "@/layouts/PublicLayout";
import { Home } from "@/pages/public/Home";
import { About } from "@/pages/public/About";
import { Solutions } from "@/pages/public/Solutions";
import { HowItWorks } from "@/pages/public/HowItWorks";
import { Industries } from "@/pages/public/Industries";
import { Contact } from "@/pages/public/Contact";
import { ForgotPassword, Login, Register, ResetPassword } from "@/pages/public/Auth";
import { NotFound } from "@/pages/public/NotFound";

// The authenticated application (charts, playground) loads on demand.
const AppLayout = lazy(() => import("@/layouts/AppLayout").then((m) => ({ default: m.AppLayout })));
const Overview = lazy(() => import("@/pages/app/Overview").then((m) => ({ default: m.Overview })));
const AgentPage = lazy(() => import("@/pages/app/AgentConfig").then((m) => ({ default: m.AgentConfig })));
const Playground = lazy(() => import("@/pages/app/Playground").then((m) => ({ default: m.Playground })));
const Conversations = lazy(() => import("@/pages/app/Conversations").then((m) => ({ default: m.Conversations })));
const ConversationView = lazy(() => import("@/pages/app/ConversationView").then((m) => ({ default: m.ConversationView })));
const Actions = lazy(() => import("@/pages/app/Actions").then((m) => ({ default: m.Actions })));
const AnalyticsPage = lazy(() => import("@/pages/app/Analytics").then((m) => ({ default: m.AnalyticsPage })));
const Knowledge = lazy(() => import("@/pages/app/Knowledge").then((m) => ({ default: m.Knowledge })));
const SettingsPage = lazy(() => import("@/pages/app/Settings").then((m) => ({ default: m.SettingsPage })));

const Loading = () => (
  <div style={{ display: "grid", placeItems: "center", minHeight: "50vh", color: "var(--text-3)" }}>
    <span className="spinner" />
  </div>
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route element={<PublicLayout />}>
                <Route index element={<Home />} />
                <Route path="about" element={<About />} />
                <Route path="solutions" element={<Solutions />} />
                <Route path="how-it-works" element={<HowItWorks />} />
                <Route path="industries" element={<Industries />} />
                <Route path="contact" element={<Contact />} />
                <Route path="login" element={<Login />} />
                <Route path="register" element={<Register />} />
                <Route path="forgot-password" element={<ForgotPassword />} />
                <Route path="reset-password" element={<ResetPassword />} />
                <Route path="*" element={<NotFound />} />
              </Route>
              <Route
                path="app"
                element={
                  <RequireAuth>
                    <AppLayout />
                  </RequireAuth>
                }
              >
                <Route index element={<Suspense fallback={<Loading />}><Overview /></Suspense>} />
                <Route path="agent" element={<Suspense fallback={<Loading />}><AgentPage /></Suspense>} />
                <Route path="playground" element={<Suspense fallback={<Loading />}><Playground /></Suspense>} />
                <Route path="conversations" element={<Suspense fallback={<Loading />}><Conversations /></Suspense>} />
                <Route path="conversations/:id" element={<Suspense fallback={<Loading />}><ConversationView /></Suspense>} />
                <Route path="actions" element={<Suspense fallback={<Loading />}><Actions /></Suspense>} />
                <Route path="analytics" element={<Suspense fallback={<Loading />}><AnalyticsPage /></Suspense>} />
                <Route path="knowledge" element={<Suspense fallback={<Loading />}><Knowledge /></Suspense>} />
                <Route path="settings" element={<Suspense fallback={<Loading />}><SettingsPage /></Suspense>} />
              </Route>
            </Routes>
          </Suspense>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
