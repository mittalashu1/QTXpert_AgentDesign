import { KeyboardEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  CircularProgress,
  FormControlLabel,
  IconButton,
  InputAdornment,
  Link,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  AlternateEmailRounded,
  AutoAwesomeRounded,
  InsightsRounded,
  LockOutlined,
  PlayCircleOutlineRounded,
  VisibilityOffOutlined,
  VisibilityOutlined,
} from "@mui/icons-material";
import axios from "axios";
import { useAuth } from "@/contexts/AuthContext";

interface LoginFormValues {
  email: string;
  password: string;
  rememberEmail: boolean;
}

const REMEMBERED_EMAIL_KEY = "qtxpert-remembered-email";

const capabilities = [
  {
    icon: <AutoAwesomeRounded fontSize="small" />,
    title: "Intelligent test design",
    detail: "Turn requirements into traceable, risk-aware test coverage.",
  },
  {
    icon: <PlayCircleOutlineRounded fontSize="small" />,
    title: "Connected execution",
    detail: "Coordinate web, mobile, and API quality workflows.",
  },
  {
    icon: <InsightsRounded fontSize="small" />,
    title: "Release intelligence",
    detail: "See evidence, risk, and readiness in one workspace.",
  },
];

export default function LoginPage() {
  const { login, user, isLoading: isAuthLoading } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [capsLockOn, setCapsLockOn] = useState(false);
  const rememberedEmail = localStorage.getItem(REMEMBERED_EMAIL_KEY) ?? "";
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    defaultValues: {
      email: rememberedEmail,
      password: "",
      rememberEmail: Boolean(rememberedEmail),
    },
    mode: "onTouched",
  });

  useEffect(() => {
    if (!isAuthLoading && user) navigate("/", { replace: true });
  }, [isAuthLoading, navigate, user]);

  const onSubmit = async (values: LoginFormValues) => {
    setError(null);
    const email = values.email.trim().toLowerCase();
    try {
      await login(email, values.password);
      if (values.rememberEmail) {
        localStorage.setItem(REMEMBERED_EMAIL_KEY, email);
      } else {
        localStorage.removeItem(REMEMBERED_EMAIL_KEY);
      }
      navigate("/", { replace: true });
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const status = err.response?.status;
        const detail = err.response?.data?.detail;
        if (status === 401) {
          setError("Email or password is incorrect.");
        } else if (status === 403) {
          setError("Your account cannot sign in right now. Contact your workspace administrator.");
        } else if (status === 429) {
          setError("Too many sign-in attempts. Please wait a moment and try again.");
        } else if (!err.response) {
          setError("We couldn't connect to QTXpert. Check your connection and try again.");
        } else if (typeof detail === "string" && status && status < 500) {
          setError(detail);
        } else {
          setError("QTXpert is temporarily unavailable. Please try again shortly.");
        }
      } else {
        setError("Sign-in failed unexpectedly. Please try again.");
      }
    }
  };

  const updateCapsLock = (event: KeyboardEvent<HTMLInputElement>) => {
    setCapsLockOn(event.getModifierState("CapsLock"));
  };

  if (isAuthLoading || user) {
    return (
      <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", bgcolor: "#F6F8FC" }}>
        <CircularProgress aria-label="Loading your QTXpert workspace" />
      </Box>
    );
  }

  return (
    <Box
      component="main"
      sx={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: { xs: "1fr", md: "minmax(430px, 1.05fr) minmax(500px, 0.95fr)" },
        bgcolor: "#F6F8FC",
      }}
    >
      <Box
        component="section"
        aria-label="QTXpert platform overview"
        sx={{
          position: "relative",
          overflow: "hidden",
          display: { xs: "none", md: "flex" },
          flexDirection: "column",
          justifyContent: "space-between",
          minHeight: "100vh",
          p: { md: 6, lg: 8 },
          color: "white",
          background:
            "radial-gradient(circle at 78% 18%, rgba(34,211,238,.22), transparent 26%), radial-gradient(circle at 18% 82%, rgba(99,102,241,.35), transparent 34%), linear-gradient(145deg, #101828 0%, #1E1B4B 58%, #312E81 100%)",
        }}
      >
        <Box
          aria-hidden="true"
          sx={{
            position: "absolute",
            inset: 0,
            opacity: 0.12,
            backgroundImage:
              "linear-gradient(rgba(255,255,255,.18) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.18) 1px, transparent 1px)",
            backgroundSize: "56px 56px",
            maskImage: "linear-gradient(to bottom, black, transparent 82%)",
          }}
        />

        <Stack spacing={1} sx={{ position: "relative" }}>
          <Box
            sx={{
              display: "inline-flex",
              alignSelf: "flex-start",
              alignItems: "center",
              bgcolor: "rgba(255,255,255,.96)",
              px: 1.5,
              py: 0.8,
              borderRadius: 2.25,
              boxShadow: "0 8px 28px rgba(0,0,0,.15)",
            }}
          >
            <Box component="img" src="/qtxpert-logo.svg" alt="QTXpert" sx={{ display: "block", width: 165, height: "auto" }} />
          </Box>
          <Typography variant="caption" sx={{ color: "rgba(255,255,255,.62)", pl: 0.5, letterSpacing: ".08em" }}>
            QUALITY ENGINEERING INTELLIGENCE
          </Typography>
        </Stack>

        <Box sx={{ position: "relative", maxWidth: 620, my: 8 }}>
          <Typography
            component="h1"
            sx={{ fontSize: { md: 46, lg: 58 }, lineHeight: 1.05, fontWeight: 750, letterSpacing: "-0.045em" }}
          >
            From requirement to release confidence.
          </Typography>
          <Typography sx={{ mt: 2.5, maxWidth: 540, color: "rgba(255,255,255,.72)", fontSize: 18, lineHeight: 1.65 }}>
            Design, automate, and govern software quality with an AI-assisted workspace built for modern engineering teams.
          </Typography>

          <Stack spacing={2.25} sx={{ mt: 5 }}>
            {capabilities.map((capability) => (
              <Stack key={capability.title} direction="row" spacing={2} alignItems="flex-start">
                <Box
                  sx={{
                    width: 38,
                    height: 38,
                    flex: "0 0 auto",
                    borderRadius: 2,
                    display: "grid",
                    placeItems: "center",
                    color: "#67E8F9",
                    bgcolor: "rgba(255,255,255,.08)",
                    border: "1px solid rgba(255,255,255,.14)",
                  }}
                >
                  {capability.icon}
                </Box>
                <Box>
                  <Typography sx={{ fontWeight: 700 }}>{capability.title}</Typography>
                  <Typography variant="body2" sx={{ mt: 0.25, color: "rgba(255,255,255,.62)" }}>
                    {capability.detail}
                  </Typography>
                </Box>
              </Stack>
            ))}
          </Stack>
        </Box>

        <Typography variant="caption" sx={{ position: "relative", color: "rgba(255,255,255,.48)" }}>
          Enterprise-ready quality engineering workspace
        </Typography>
      </Box>

      <Box
        component="section"
        aria-label="Sign in"
        sx={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          px: { xs: 2, sm: 4, lg: 8 },
          py: 4,
          background:
            "radial-gradient(circle at 90% 8%, rgba(79,70,229,.08), transparent 30%), #F6F8FC",
        }}
      >
        <Box sx={{ width: "100%", maxWidth: 470 }}>
          <Box sx={{ display: { xs: "block", md: "none" }, mb: 4 }}>
            <Box component="img" src="/qtxpert-logo.svg" alt="QTXpert" sx={{ display: "block", width: 155, height: "auto" }} />
          </Box>

          <Card
            elevation={0}
            sx={{
              borderRadius: 4,
              border: "1px solid #E4E7EC",
              boxShadow: "0 24px 70px rgba(16,24,40,.10)",
              bgcolor: "rgba(255,255,255,.96)",
            }}
          >
            <CardContent sx={{ p: { xs: 3, sm: 5 } }}>
              <Typography component="h2" sx={{ color: "#101828", fontSize: 30, fontWeight: 750, letterSpacing: "-0.035em" }}>
                Welcome back
              </Typography>
              <Typography sx={{ mt: 1, mb: 3.5, color: "#667085" }}>
                Sign in to continue to your QTXpert workspace.
              </Typography>

              {error && (
                <Alert severity="error" role="alert" aria-live="assertive" sx={{ mb: 2.5, borderRadius: 2 }}>
                  {error}
                </Alert>
              )}

              <Box component="form" noValidate onSubmit={handleSubmit(onSubmit)}>
                <Stack spacing={2.25}>
                  <TextField
                    label="Work email"
                    type="email"
                    fullWidth
                    autoFocus
                    autoComplete="email"
                    placeholder="name@company.com"
                    error={Boolean(errors.email)}
                    helperText={errors.email?.message}
                    InputProps={{
                      startAdornment: (
                        <InputAdornment position="start">
                          <AlternateEmailRounded fontSize="small" sx={{ color: "#98A2B3" }} />
                        </InputAdornment>
                      ),
                    }}
                    sx={{ "& .MuiOutlinedInput-root": { minHeight: 52, borderRadius: 2.5 } }}
                    {...register("email", {
                      required: "Enter your work email.",
                      pattern: {
                        value: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
                        message: "Enter a valid email address.",
                      },
                    })}
                  />

                  <Box>
                    <TextField
                      label="Password"
                      type={showPassword ? "text" : "password"}
                      fullWidth
                      autoComplete="current-password"
                      error={Boolean(errors.password)}
                      helperText={errors.password?.message}
                      onKeyUp={updateCapsLock}
                      onKeyDown={updateCapsLock}
                      InputProps={{
                        startAdornment: (
                          <InputAdornment position="start">
                            <LockOutlined fontSize="small" sx={{ color: "#98A2B3" }} />
                          </InputAdornment>
                        ),
                        endAdornment: (
                          <InputAdornment position="end">
                            <IconButton
                              aria-label={showPassword ? "Hide password" : "Show password"}
                              edge="end"
                              onClick={() => setShowPassword((visible) => !visible)}
                            >
                              {showPassword ? <VisibilityOffOutlined /> : <VisibilityOutlined />}
                            </IconButton>
                          </InputAdornment>
                        ),
                      }}
                      sx={{ "& .MuiOutlinedInput-root": { minHeight: 52, borderRadius: 2.5 } }}
                      {...register("password", { required: "Enter your password." })}
                    />
                    {capsLockOn && (
                      <Typography role="status" variant="caption" sx={{ display: "block", mt: 0.75, ml: 1.75, color: "#B54708" }}>
                        Caps Lock is on
                      </Typography>
                    )}
                  </Box>

                  <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2}>
                    <FormControlLabel
                      control={<Checkbox size="small" {...register("rememberEmail")} />}
                      label={<Typography variant="body2">Remember email</Typography>}
                      sx={{ color: "#475467", m: 0 }}
                    />
                    <Link
                      href="mailto:qtxpert.ai@gmail.com?subject=QTXpert%20password%20assistance"
                      underline="hover"
                      variant="body2"
                      sx={{ fontWeight: 650, whiteSpace: "nowrap" }}
                    >
                      Forgot password?
                    </Link>
                  </Stack>

                  <Button
                    type="submit"
                    variant="contained"
                    size="large"
                    disabled={isSubmitting}
                    sx={{
                      minHeight: 52,
                      borderRadius: 2.5,
                      fontWeight: 750,
                      textTransform: "none",
                      boxShadow: "0 10px 22px rgba(79,70,229,.24)",
                      "&:hover": { boxShadow: "0 12px 28px rgba(79,70,229,.32)" },
                    }}
                  >
                    {isSubmitting ? (
                      <Stack direction="row" spacing={1.25} alignItems="center">
                        <CircularProgress size={18} color="inherit" />
                        <span>Signing in…</span>
                      </Stack>
                    ) : (
                      "Sign in"
                    )}
                  </Button>
                </Stack>
              </Box>

              <Typography variant="body2" align="center" sx={{ mt: 3, color: "#667085" }}>
                Need help?{" "}
                <Link href="mailto:qtxpert.ai@gmail.com?subject=QTXpert%20workspace%20support" underline="hover" sx={{ fontWeight: 650 }}>
                  Contact your workspace administrator
                </Link>
              </Typography>
            </CardContent>
          </Card>

          <Stack direction="row" justifyContent="center" spacing={2.5} sx={{ mt: 3 }}>
            <Typography variant="caption" sx={{ color: "#98A2B3" }}>© 2026 QTXpert</Typography>
            <Typography variant="caption" sx={{ color: "#98A2B3" }}>Secure workspace access</Typography>
          </Stack>
        </Box>
      </Box>
    </Box>
  );
}
