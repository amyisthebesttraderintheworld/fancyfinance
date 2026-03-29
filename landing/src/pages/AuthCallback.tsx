import React, { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/**
 * AuthCallback.tsx
 * 
 * This page handles the direct redirect from the backend's Telegram login flow.
 * It's responsible for capturing the token from the URL and storing it in localStorage.
 */

const TOKEN_KEY = 'fancyfinance_member_dashboard_token';

const AuthCallback = () => {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const accessToken = params.get('access');

    if (accessToken) {
      console.log("Captured access token from URL at /auth/callback");
      // Backend already validated the Telegram HMAC and issued a token.
      localStorage.setItem(TOKEN_KEY, accessToken);
      navigate('/dashboard', { replace: true });
      return;
    }

    // No token — something went wrong upstream. Send back to login.
    console.log("No token found at /auth/callback, redirecting to home");
    navigate('/');
  }, [location, navigate]);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-slate-950 text-white gap-4">
      <div className="text-xl font-semibold">Authenticating…</div>
      <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
    </div>
  );
};

export default AuthCallback;
