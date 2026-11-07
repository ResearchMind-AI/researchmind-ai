import { useEffect } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { PageLoading } from "./components/ui";
import LoginPage from "./pages/LoginPage";
import AppShell from "./pages/AppShell";
import HomePage from "./pages/HomePage";
import SessionLayout, { useSession } from "./pages/SessionLayout";
import ExploreView from "./pages/ExploreView";
import PapersView from "./pages/PapersView";
import ThemesView from "./pages/ThemesView";
import GapsView from "./pages/GapsView";
import WriteView from "./pages/WriteView";
import ShareView from "./pages/ShareView";

// Old links (before Themes and Gaps moved under Explore, and Ask became a panel) still work.
function OldGapLink() { return <Navigate to={`../explore/gaps/${useParams().gapId}`} replace />; }
function OpenPartner() {
  const { openPartner } = useSession();
  useEffect(() => { openPartner(); }, [openPartner]);
  return <Navigate to="../papers" replace />;
}

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
          <Route path="explore" element={<ExploreView />}>
            <Route index element={<Navigate to="themes" replace />} />
            <Route path="themes" element={<ThemesView />} />
            <Route path="gaps" element={<GapsView />} />
            <Route path="gaps/:gapId" element={<GapsView />} />
          </Route>
          <Route path="write" element={<WriteView />} />
          <Route path="themes" element={<Navigate to="../explore/themes" replace />} />
          <Route path="gaps" element={<Navigate to="../explore/gaps" replace />} />
          <Route path="gaps/:gapId" element={<OldGapLink />} />
          <Route path="chat" element={<OpenPartner />} />
          <Route path="share" element={<ShareView />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
