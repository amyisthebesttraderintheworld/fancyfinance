import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import Index from "./pages/Index.tsx";
import Dashboard from "./pages/Dashboard.tsx";
import NotFound from "./pages/NotFound.tsx";
import { AuthProvider } from "@/contexts/AuthContext";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            {/* Main Landing Page */}
            <Route path="/" element={<Index />} />
            
            {/* The Unified Dashboard Route */}
            <Route path="/dashboard" element={<Dashboard />} />
            
            {/* Legacy/Alternative Member Route (Alias) */}
            <Route path="/dashboard/member" element={<Dashboard />} />
            
            {/* Handle Login Redirects from Backend */}
            <Route path="/dashboard/login" element={<Navigate to="/" replace />} />
            
            {/* Catch-all Not Found */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
