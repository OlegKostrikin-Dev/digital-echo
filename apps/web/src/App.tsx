import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import HomePage from "./pages/HomePage";
import CasesPage from "./pages/CasesPage";
import SearchPage from "./pages/SearchPage";
import CompanyPage from "./pages/CompanyPage";
import GuestLandingPage from "./pages/GuestLandingPage";
import AccessPage from "./pages/AccessPage";
import AdminLoginPage from "./pages/AdminLoginPage";
import AdminInvitesPage from "./pages/AdminInvitesPage";
import { RequireAuth } from "./context/AuthContext";

export default function App() {
  return (
    <Routes>
        <Route path="/" element={<GuestLandingPage />} />
        <Route path="/access" element={<AccessPage />} />
        <Route path="/admin/login" element={<AdminLoginPage />} />
        <Route path="/admin/invites" element={<AdminInvitesPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/home" element={<HomePage />} />
            <Route path="/cases" element={<CasesPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/company/:bin" element={<CompanyPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
  );
}
