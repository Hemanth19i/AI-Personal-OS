import { NavLink } from "react-router-dom";

/** Three pillars (Design Candidate v1.0): Ask · Search · Library.
 *  The graph is a lens entered from content, not a pillar. */

const AskIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 5h16v11H9l-5 4z" strokeLinejoin="round" />
  </svg>
);

const SearchIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="10.5" cy="10.5" r="6.5" />
    <line x1="15.5" y1="15.5" x2="20.5" y2="20.5" strokeLinecap="round" />
  </svg>
);

const LibraryIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <rect x="4" y="4" width="4.5" height="16" rx="1" />
    <rect x="10" y="4" width="4.5" height="16" rx="1" />
    <path d="M16.5 5.2 20 4.5l1.8 15.2-3.6.7z" strokeLinejoin="round" />
  </svg>
);

export function Rail() {
  return (
    <nav className="rail" aria-label="Primary">
      <div className="rail-brand voice">AI Personal OS</div>
      <NavLink to="/" end>
        <AskIcon />
        <span>Ask</span>
      </NavLink>
      <NavLink to="/search">
        <SearchIcon />
        <span>Search</span>
      </NavLink>
      <NavLink to="/library">
        <LibraryIcon />
        <span>Library</span>
      </NavLink>
      <div className="rail-foot">
        <span className="dot" style={{ background: "var(--brass)" }} />
        <span>default</span>
      </div>
    </nav>
  );
}
