import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import AppLayout from "@/components/AppLayout";
import LoginPage from "@/pages/LoginPage";
import GenerateTestCasesPage from "@/pages/GenerateTestCasesPage";
import HistoryPage from "@/pages/HistoryPage";
import SettingsPage from "@/pages/SettingsPage";
import ApiConfigurationPage from "@/pages/ApiConfigurationPage";
import ProfilePage from "@/pages/ProfilePage";
import PromptLibraryPage from "@/pages/PromptLibraryPage";
import HelpPage from "@/pages/HelpPage";
import UsersPage from "@/pages/UsersPage";
import DocumentIntelligencePage from "@/pages/DocumentIntelligencePage";
import DashboardPage from "@/pages/DashboardPage";
import TestExecutionPage from "@/pages/TestExecutionPage";
import TestReportsPage from "@/pages/TestReportsPage";
import AutopilotPage from "@/pages/AutopilotPage";
import UploadsPage from "@/pages/UploadsPage";
import CostCenterPage from "@/pages/CostCenterPage";
import { Alert, Box, Button, CircularProgress } from "@mui/material";

const COST_ADMIN_EMAIL = "admin@qtxpert.com";

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const { user, isLoading, authUnavailable, retryAuth } = useAuth();
  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh">
        <CircularProgress />
      </Box>
    );
  }
  if (authUnavailable) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="100vh" px={2}>
        <Alert
          severity="warning"
          action={
            <Button color="inherit" size="small" onClick={retryAuth}>
              Retry
            </Button>
          }
        >
          The authentication service is temporarily unavailable. Your session is preserved; retry in a moment.
        </Alert>
      </Box>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function AdminRoute({ children }: { children: JSX.Element }) {
  const { user } = useAuth();
  return user?.role === "admin" ? children : <Navigate to="/" replace />;
}

function CostAdminRoute({ children }: { children: JSX.Element }) {
  const { user } = useAuth();
  const allowed = user?.role === "admin" && user.email.trim().toLowerCase() === COST_ADMIN_EMAIL;
  return allowed ? children : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
        <Route index element={<DashboardPage />} />
        <Route path="autopilot" element={<AutopilotPage />} />
        <Route path="documents" element={<DocumentIntelligencePage />} />
        <Route path="design" element={<GenerateTestCasesPage />} />
        <Route path="generate" element={<Navigate to="/design" replace />} />
        <Route path="test-data/uploads" element={<UploadsPage />} />
        <Route path="uploads" element={<Navigate to="/test-data/uploads" replace />} />
        <Route path="execution" element={<TestExecutionPage />} />
        <Route path="reports" element={<TestReportsPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/api-configuration" element={<ApiConfigurationPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="prompt-library" element={<PromptLibraryPage />} />
        <Route path="help" element={<HelpPage />} />
        <Route path="administration/users" element={<AdminRoute><UsersPage /></AdminRoute>} />
        <Route path="cost-center" element={<CostAdminRoute><CostCenterPage /></CostAdminRoute>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
