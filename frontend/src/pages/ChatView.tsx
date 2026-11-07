import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { MessageSquare } from "lucide-react";
import ChatThread from "../components/ChatThread";
import { Empty } from "../components/ui";
import { useSession } from "./SessionLayout";

export default function ChatView() {
  const { sid, session, papers, paperMap } = useSession();
  const location = useLocation();
  const navigate = useNavigate();
  // Take a handed-over question once, and clear it so a refresh doesn't ask it again.
  const [initial] = useState(() => (location.state as { ask?: string } | null)?.ask);
  useEffect(() => { if (initial) navigate(location.pathname, { replace: true, state: null }); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!papers.length) {
    return <Empty icon={<MessageSquare size={22} />} title="No papers to ask about yet">Find papers first; answers are drawn only from this session's papers.</Empty>;
  }
  const topic = session.topic || session.title;
  return (
    <div className="mx-auto w-full max-w-[820px]">
      <ChatThread sid={sid} paperMap={paperMap} canAsk={session.can_edit} initialQuestion={initial}
        suggestions={[
          "What are the main methods used across these papers?",
          "Where do the findings disagree?",
          `What evidence is there from real-world settings on ${topic.length > 60 ? "this topic" : topic}?`,
          "Which datasets or populations are most studied?",
        ]} />
    </div>
  );
}
