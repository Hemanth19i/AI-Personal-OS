import { Outlet } from "react-router-dom";
import { Rail } from "./Rail";
import { TopBar } from "./TopBar";

/** The Study's frame: rail (the pillars) + top chrome + one reading surface. */
export function Shell() {
  return (
    <div className="shell">
      <Rail />
      <div className="content">
        <TopBar />
        <main className="main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
