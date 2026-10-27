import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Outlet, matchPath, useLocation, useNavigate } from "react-router-dom";

import { Icon, Loading } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../services/auth";

function Brand({ to }: { to: string }) {
  return (
    <Link to={to} className="brand">
      <span className="brand-mark"><Icon name="logo" /></span>
      <span className="brand-text">Research Data<br />Analysis</span>
    </Link>
  );
}

/** True while the viewport is at most `max` px wide (false where matchMedia is unavailable). */
function useNarrow(max: number): boolean {
  const query = `(max-width: ${max}px)`;
  const [narrow, setNarrow] = useState(() => (typeof window.matchMedia === "function" ? window.matchMedia(query).matches : false));
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const update = () => setNarrow(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return narrow;
}

function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "?";
}

/** Shell for signed-in pages: a persistent sidebar (icon-only inside a project, to leave room for the workflow steps). */
export default function AppLayout() {
  const { user, loading, signOut, can } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const { data: notifications } = useApi<{ unread: number }>(user ? "/notifications?unread_only=true" : null);
  const inProject = !!matchPath("/projects/:projectId/*", location.pathname) && !location.pathname.endsWith("/projects/new");

  const narrow = useNarrow(1100);
  useEffect(() => setMenuOpen(false), [location.pathname]);

  if (loading) return <main className="page"><Loading label="Checking your session" /></main>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;

  const unread = notifications?.unread ?? 0;
  const item = (to: string, icon: string, label: string) => (
    <NavLink to={to} title={label}>
      <Icon name={icon} />
      <span className="nav-label">{label}</span>
    </NavLink>
  );

  return (
    <div className={`shell ${inProject || narrow ? "compact" : ""} ${menuOpen ? "menu-open" : ""}`}>
      <aside className="sidebar">
        <Brand to="/dashboard" />
        <nav aria-label="Main">
          <div className="nav-group">Workspace</div>
          {item("/dashboard", "home", "Dashboard")}
          {item("/projects", "folder", "My projects")}
          {item("/power", "calc", "Sample size")}
          {can("admin.users") && item("/admin", "shield", "Administration")}
          <div className="nav-group">Account</div>
          <NavLink to="/settings" title="Settings">
            <Icon name="settings" />
            <span className="nav-label">Settings{unread > 0 ? ` (${unread} new)` : ""}</span>
            {unread > 0 && <span className="nav-count" aria-hidden="true">{unread}</span>}
            {unread > 0 && <span className="nav-dot" aria-hidden="true" />}
          </NavLink>
        </nav>
        <div className="side-spacer" />
        <Link to="/profile" className="user-card" title="Your profile">
          <span className="avatar" aria-hidden="true">{initials(user.full_name)}</span>
          <span className="who"><strong>{user.full_name}</strong><span>View profile</span></span>
        </Link>
        <nav aria-label="Session">
          <button type="button" className="side-btn" title="Sign out" onClick={() => signOut().then(() => navigate("/"))}>
            <Icon name="logout" />
            <span className="nav-label">Sign out</span>
          </button>
        </nav>
      </aside>
      <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />
      <div className="shell-main">
        <div className="mobilebar">
          <button type="button" className="menu-btn" aria-label="Open menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>
            <Icon name="menu" />
          </button>
          <Brand to="/dashboard" />
        </div>
        <Outlet />
      </div>
      <nav className="tabbar" aria-label="Primary">
        <NavLink to="/dashboard"><Icon name="home" /><span>Home</span></NavLink>
        <NavLink to="/projects"><Icon name="folder" /><span>Projects</span></NavLink>
        <NavLink to="/power"><Icon name="calc" /><span>Sample size</span></NavLink>
        <NavLink to="/settings">
          <Icon name="settings" /><span>Settings</span>
          {unread > 0 && <span className="nav-dot" aria-hidden="true" />}
        </NavLink>
      </nav>
    </div>
  );
}

export function PublicLayout() {
  const { user } = useAuth();
  return (
    <>
      <header className="pubbar">
        <Brand to="/" />
        <span className="grow" />
        {user ? <Link className="btn primary small" to="/dashboard">Open dashboard</Link> : (
          <>
            <Link className="btn quiet" to="/login">Sign in</Link>
            <Link className="btn primary small" to="/register">Create account</Link>
          </>
        )}
      </header>
      <Outlet />
    </>
  );
}
