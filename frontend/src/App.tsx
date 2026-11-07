import { Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { PageLoading } from "./components/ui";
import LoginPage from "./pages/LoginPage";
import AppShell from "./pages/AppShell";
import HomePage from "./pages/HomePage";
import SessionLayout from "./pages/SessionLayout";
import PapersView from "./pages/PapersView";
import ThemesView from "./pages/ThemesView";
import GapsView from "./pages/GapsView";
import ChatView from "./pages/ChatView";
import WriteView from "./pages/WriteView";
import ShareView from "./pages/ShareView";

export default function App() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false, staleTime: Infinity });

  if (me.isLoading) return <div className="flex min-h-screen items-center justify-center"><PageLoading /></div>;
  if (me.error && !(me.error instanceof ApiError && me.error.status === 401)) {
    return <div className="p-8 text-ink-muted">Can't reach the server. Refresh to try again.</div>;
  }
  if (!me.data) return <LoginPage />;

  return (
    <Routes>
      <Route element={<AppShell user={me.data} />}>
        <Route index element={<HomePage />} />
        <Route path="s/:sid" element={<SessionLayout />}>
          <Route index element={<Navigate to="papers" replace />} />
          <Route path="papers" element={<PapersView />} />
          <Route path="themes" element={<ThemesView />} />
          <Route path="gaps" element={<GapsView />} />
          <Route path="gaps/:gapId" element={<GapsView />} />
          <Route path="chat" element={<ChatView />} />
          <Route path="write" element={<WriteView />} />
          <Route path="share" element={<ShareView />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
