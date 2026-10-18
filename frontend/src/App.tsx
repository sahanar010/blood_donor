import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { BASE } from "./api";
import { useAuth } from "./auth";
import Donor from "./pages/Donor";
import Hospital from "./pages/Hospital";
import Login from "./pages/Login";

function Guard({ role, children }: { role: "DONOR" | "HOSPITAL"; children: ReactElement }) {
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/login" replace />;
  return auth.role === role ? children : <Navigate to="/" replace />;
}

function Home() {
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/login" replace />;
  if (auth.role === "HOSPITAL") return <Navigate to="/hospital" replace />;
  if (auth.role === "DONOR") return <Navigate to="/donor" replace />;
  return <p className="p-6">Admins verify hospitals and donors in the API docs: <a className="underline" href={`${BASE}/docs`}>{BASE}/docs</a></p>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/hospital" element={<Guard role="HOSPITAL"><Hospital /></Guard>} />
      <Route path="/donor" element={<Guard role="DONOR"><Donor /></Guard>} />
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
