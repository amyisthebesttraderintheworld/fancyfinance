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

  useEffect(() => {
    // The backend issues a signed JWT as ?access=<token>, which Dashboard.tsx
    // saves under TOKEN_KEY. That token IS the session — no separate user object needed.
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) {
      setUser({ token });
    }
    setLoading(false);
  }, []);

  const logout = () => {
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
