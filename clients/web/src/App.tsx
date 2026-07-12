import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Shell } from "./shell/Shell";
import { Ask } from "./routes/Ask";
import { Search } from "./routes/Search";
import { Library } from "./routes/Library";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Ask />} />
          <Route path="search" element={<Search />} />
          <Route path="library" element={<Library />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
