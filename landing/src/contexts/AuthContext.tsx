import React, { createContext, useState, useContext, useEffect } from 'react';

const TOKEN_KEY = 'fancyfinance_member_dashboard_token';

interface AuthUser {
  token: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  loading: true,
  logout: () => {},
});

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const initializeAuth = () => {
    // Check localStorage for an existing session
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) {
      console.log("Auth initialized from localStorage token");
      setUser({ token });
    } else {
      console.log("No token found in localStorage during initialization");
      setUser(null);
    }
    setLoading(false);
  };

  useEffect(() => {
    initializeAuth();
    
    // Listen for storage changes in other tabs
    window.addEventListener('storage', initializeAuth);
    return () => window.removeEventListener('storage', initializeAuth);
  }, []);

  const logout = () => {
    console.log("User logged out");
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
