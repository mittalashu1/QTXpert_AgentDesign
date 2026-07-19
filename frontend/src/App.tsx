import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import AppLayout from "@/components/AppLayout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import RequirementUploadPage from "@/pages/RequirementUploadPage";
import GenerateTestCasesPage from "@/pages/GenerateTestCasesPage";
import HistoryPage from "@/pages/HistoryPage";
import SettingsPage from "@/pages/SettingsPage";
import ApiConfigurationPage from "@/pages/ApiConfigurationPage";
import ProfilePage from "@/pages/ProfilePage";
import PromptLibraryPage from "@/pages/PromptLibraryPage";
import HelpPage from "@/pages/HelpPage";
import { CircularProgress, Box } from "@mui/material";

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
        <CircularProgress />
      </Box>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="requirements/upload" element={<RequirementUploadPage />} />
        <Route path="generate" element={<GenerateTestCasesPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/api-configuration" element={<ApiConfigurationPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="prompt-library" element={<PromptLibraryPage />} />
        <Route path="help" element={<HelpPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
