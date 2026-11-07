import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useSession } from "./SessionLayout";

const ABOUT = {
  themes: <><b className="text-ink">Themes</b> group your kept papers by what they study, with each group's key findings. They show the shape of the field at a glance and update when you change your papers.</>,
  gaps: <><b className="text-ink">Gaps</b> are questions your papers don't answer yet: possible directions for your own research. Track the ones that interest you; each is checked against recent work.</>,
};

export default function ExploreView() {
  const ctx = useSession();
  const onGaps = /\/explore\/gaps/.test(useLocation().pathname);
  const tab = ({ isActive }: { isActive: boolean }) =>
    `flex h-8 items-center gap-1.5 rounded-[7px] px-3.5 text-[13px] font-semibold no-underline ${isActive ? "bg-white text-ink shadow-sm" : "text-ink-muted hover:text-ink"}`;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <nav className="flex gap-1 self-start rounded-[10px] bg-chip p-1" aria-label="Explore">
          <NavLink to="themes" className={tab}>Themes <span className="rounded-full bg-chip px-1.5 text-xs">{ctx.session.theme_count}</span></NavLink>
          <NavLink to="gaps" className={tab}>Gaps <span className="rounded-full bg-chip px-1.5 text-xs">{ctx.session.gap_count}</span></NavLink>
        </nav>
        <p className="max-w-3xl text-sm text-ink-muted">{onGaps ? ABOUT.gaps : ABOUT.themes}</p>
      </div>
      <Outlet context={ctx} />
    </div>
  );
}
