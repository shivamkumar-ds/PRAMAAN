import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

// Attach the JWT (if present) to every outgoing request. Token lives in
// localStorage -- this is a plain web app, not a sandboxed artifact, so
// localStorage is the normal, correct choice here for an MVP.
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("pramaan_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On any 401, the token is stale/invalid -- clear it and force back to
// login rather than showing a confusing broken screen.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("pramaan_token");
      localStorage.removeItem("pramaan_user");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

/**
 * Every backend error (422 validation, or any other failure) is surfaced
 * through FastAPI's HTTPValidationError / HTTPException shape. This pulls
 * a single human-readable string out of whatever shape actually comes
 * back, so every page can display errors the same way instead of each
 * page guessing at response.data structure.
 */
export function extractErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    if (data?.detail) {
      if (typeof data.detail === "string") return data.detail;
      if (Array.isArray(data.detail)) {
        return data.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ");
      }
    }
    if (error.message) return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}
